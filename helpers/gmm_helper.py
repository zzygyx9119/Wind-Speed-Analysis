from .shared_imports import *


def group_gmm_param_from_gmm_param_array(gmm_param_array, sort_group=True):
    from operator import itemgetter
    from .app_helper import chunks
    # from 17-1 -> 6-n array
    gmm = list(chunks(gmm_param_array, 6))
    if sort_group:
        gmm = sorted(gmm, key=itemgetter(0), reverse=True)  # reorder by fraction, from big to small
    return gmm


# GMM result
def read_gmm_em_result(clf):
    gmm_em_result = []
    for i in range(clf.n_components):
        weight = clf.weights_[i]
        meanx, meany = clf.means_[i].tolist()
        sigx, sigy = np.sqrt(clf.covariances_[i][0, 0]), np.sqrt(clf.covariances_[i][1, 1])
        rho = clf.covariances_[i][0, 1]/(sigx*sigy)
        gaussian_params = weight, meanx, meany, sigx, sigy, rho
        gmm_em_result.extend(gaussian_params)
    return gmm_em_result


def create_gaussian_2d(meanx, meany, sigx, sigy, rho):
    from scipy.stats import multivariate_normal
    sigxy = rho*sigx*sigy
    return multivariate_normal(mean=[meanx, meany],
                               cov=[[sigx**2, sigxy], [sigxy, sigy**2]],
                               allow_singular=True)


def generate_gmm_pdf_from_grouped_gmm_param(gmm):
    gaussian_group = []
    for gaussian_param in gmm:
        f, u, v, sigu, sigv, rho = gaussian_param
        g = create_gaussian_2d(u, v, sigu, sigv, rho)
        gaussian_group.append([f, g])

    def mixed_model_pdf(points):
        result = 0
        for (f, g) in gaussian_group:
            result = result + f*g.pdf(points)
        return result
    return mixed_model_pdf


def width_height_ratio(g):
    sigx, sigy, sigxy = g[3], g[4], g[5]*g[3]*g[4]
    cov_matrix = np.matrix([[sigx**2, sigxy], [sigxy, sigy**2]])
    w, v = np.linalg.eigh(cov_matrix)
    a = np.sqrt(w[0])
    b = np.sqrt(w[1])
    return a/b


def width_height_ratios_set(gmm):
    gmm = group_gmm_param_from_gmm_param_array(gmm, sort_group=False)
    ratios_set = [width_height_ratio(g) for g in gmm]
    return np.asarray(ratios_set)


def GMM_fit_score(gmm, kde_result, points, method='square_error'):
    from .app_helper import cdf_from_pdf
    # 1. Create the GMM PDF
    if not isinstance(gmm[0], np.ndarray):
        gmm = group_gmm_param_from_gmm_param_array(gmm, sort_group=False)
    mixed_model_pdf = generate_gmm_pdf_from_grouped_gmm_param(gmm)
    # 2. Fit the model using different metrics
    gmm_pdf_result = mixed_model_pdf(points)
    if method == 'square_error':
        # 2.1 Square error
        error_array = power(gmm_pdf_result - kde_result, 2)
        result = mse_log = log(np.average(error_array))
    elif method == 'chi_square':
        # 2.2 Normalized Chi square
        error_array = power(gmm_pdf_result - kde_result, 2)
        result = chi_square_stat = log(sum(error_array/gmm_pdf_result))
    elif method == 'k_s':
        # 2.3 K-S statistc
        gmm_cdf = cdf_from_pdf(gmm_pdf_result)
        kde_cdf = cdf_from_pdf(kde_result)
        diff = abs(gmm_cdf - kde_cdf)
        result = KS_stat = log(np.amax(diff))
    return result


def fit_gmm(df, fit_method, config, number_of_gaussian=3):
    # 1. Create Input, speed_set
    sample = array(list(zip(df.x, df.y)))
    bandwidth, points, kde_kernel = config['bandwidth'], config['fitting_range'], config['kde_kernel']
    fit_limit = config['fit_limit']

    # 2. KDE + EM fitting
    kde = neighbors.KernelDensity(bandwidth=bandwidth, kernel = kde_kernel).fit(sample)
    kde_result = exp(kde.score_samples(points))

    clf = mixture.GaussianMixture(n_components=number_of_gaussian, covariance_type='full')
    clf.fit(sample)
    gmm_em_result = read_gmm_em_result(clf)

    # 3. GMM fitting
    x0 = gmm_em_result
    bonds = [(0., 0.99),(-fit_limit, fit_limit),
             (-fit_limit, fit_limit),(0., fit_limit),(0., fit_limit),(-0.99, 0.99)]*int(len(x0)/6)
    cons = [{'type': 'eq', 'fun': lambda x: sum(x[::6]) - 1},
#             {'type': 'ineq', 'fun': lambda x: width_height_ratios_set(x) - 1/3},
#             {'type': 'ineq', 'fun': lambda x: 3 - width_height_ratios_set(x)},
           ]

    result = sp.optimize.minimize(
        lambda x0: GMM_fit_score(x0, kde_result, points, method=fit_method),
        x0,
        bounds=bonds,
        constraints=cons,
        tol=0.000000000001,
        options={"maxiter": 500})

    # 4. Returns
    gmm = group_gmm_param_from_gmm_param_array(result.x)
    mixed_model_pdf = generate_gmm_pdf_from_grouped_gmm_param(gmm)
    gmm_pdf_result = mixed_model_pdf(points)

    return {
        'gmm' : gmm,
        'kde_clf': kde,
        'kde_result': kde_result,
        'gmm_pdf_result': gmm_pdf_result,
        'number_of_iteration': result.nit,
    }


def gmm_marginal_distribution(f, x, rads=linspace(0, 2*pi, num=36+1)):
    from scipy import integrate
    bins = x
    density_expected_gmm_ = [integrate.nquad(f, [[x_, x_ + 1], [0, 2 * pi]]) for x_ in bins[:-1]]
    density_speed_expected_gmm = array(list(zip(*density_expected_gmm_))[0])

    y_ = [integrate.nquad(f, [[0, x_val], [0, 2 * pi]]) for x_val in x]
    y_cdf_gmm = array(list(zip(*y_))[0])

    y_ = [integrate.nquad(f, [[0, inf], [x_-pi/36, x_+pi/36]]) for x_ in rads]
    density_dir_expected = array(list(zip(*y_))[0])
    return x, rads, density_speed_expected_gmm, y_cdf_gmm, density_dir_expected


def gmm_integration_in_direction(f, start_radian, end_radian, x):
    from scipy import integrate
    direction_prob = integrate.nquad(f, [[0, inf], [start_radian, end_radian]])[0]
    y_gmm_ = [integrate.nquad(f, [[x_-0.01, x_+0.01], [start_radian, end_radian]])
             for x_ in x]
    y_gmm = array(list(zip(*y_gmm_))[0])/direction_prob/0.02
    y_ =[integrate.nquad(f, [[0, x_val],[start_radian, end_radian]])
         for x_val in x]
    y_cdf_gmm = array(list(zip(*y_))[0])/direction_prob
    return x, y_gmm, y_cdf_gmm, direction_prob


