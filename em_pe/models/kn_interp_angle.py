import numpy as np
from scipy.interpolate import interp1d
import os
import sys
import json
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, WhiteKernel, ConstantKernel as C
from functools import lru_cache
from scipy.linalg import cholesky, cho_solve

from .model import model_base

@lru_cache(maxsize=64)
def _load_gp(fname_base):
    kernel=None
    with open(fname_base+".json",'r') as f:
        print('loading GP from json')
        my_json = json.load(f)
    my_X = np.loadtxt(fname_base+"_X.dat")
    my_y = np.loadtxt(fname_base+"_y.dat")
    my_alpha = np.loadtxt(fname_base+"_alpha.dat")
    dict_params = my_json['kernel_params']
    theta = np.array(my_json['kernel']).astype('float')
    theta = np.power(np.e, theta)
    kernel = WhiteKernel(theta[0]) + theta[1]*RBF(length_scale=theta[2:])
    gp = GaussianProcessRegressor(kernel=kernel,n_restarts_optimizer=0)
    gp.kernel_ = kernel
    dict_params_eval = {}
    for name in dict_params:
        if not('length' in name   or 'constant' in name):
            continue
        if name =="k2__k2__length_scale":
            one_space = ' '.join(dict_params[name].split())
            if one_space[1] == ' ': one_space = '['+one_space[2:]
            dict_params_eval[name] = eval(one_space.replace(' ',','))
        else:
            dict_params_eval[name] = eval(dict_params[name])
    gp.kernel_.set_params(**dict_params_eval)
    gp.X_train_ = my_X
    gp.y_train_ = my_y
    gp.alpha_ = my_alpha
    gp._y_train_std = float(my_json['y_train_std'])
    gp._y_train_mean = float(my_json['y_train_mean'])
    return gp

def _model_predict(model, inputs):#, fix_log=False):
    K = model.kernel_(model.X_train_)
    K[np.diag_indices_from(K)] += model.alpha
    model.L_ = cholesky(K, lower=True) # recalculating L matrix since this is what makes the pickled models bulky
    model._K_inv = None # has to be set to None so the GP knows to re-calculate matrices used for uncertainty
    K_trans = model.kernel_(inputs, model.X_train_)
    pred = K_trans.dot(model.alpha_)
    pred = model._y_train_std * pred + model._y_train_mean
    v = cho_solve((model.L_, True), K_trans.T)
    y_cov = model.kernel_(inputs) - K_trans.dot(v)
    err = np.sqrt(np.diag(y_cov))
    
    ### temporary hack to fix log issue
    #if fix_log:
    #    pred = 10.0**pred
    #    err = np.log(10.0) * pred * err # hopefully I propagated the error correctly

    mags = _log_lums_to_mags(pred)
    mags_error = 2.5 * err

    return mags, mags_error

def _log_lums_to_mags(log_lums):
    d = 3.086e18 # parsec in cm
    d *= 10 # distance of 10 pc
    log_flux = log_lums - np.log10(4.0 * np.pi * d**2)
    mags = -48.6 - 2.5 * log_flux
    return mags

class kn_interp_angle(model_base):
    def __init__(self, morph_comp="TP2"):
        name = "kn_interp_angle"
        param_names = ["mej_dyn", "vej_dyn", "mej_wind", "vej_wind", "theta","distance"]
        bands = ["g", "r", "i", "z", "y", "J", "H", "K"]
        model_base.__init__(self, name, param_names, bands)
        self.vectorized = True
        
        interp_loc = os.environ["INTERP_LOC"]
        if interp_loc[-1] != "/":
            interp_loc += "/"
        morph_comp_models = {"TP2": "2021_Wollaeger_TorusPeanutWind2/",
                             "TP1": "2021_Wollaeger_TorusPeanutWind1/",
                             "TS2": "2021_Wollaeger_TorusSphericalWind2/",
                             "TS1": "2021_Wollaeger_TorusSphericalWind1/",
                             }
        interp_loc += morph_comp_models[morph_comp]
        print(interp_loc)
        #interp_loc += "saved_models/2021_Wollaeger_TorusPeanut/"
        #interp_loc += "surrogate_data/2021_Wollaeger_TorusPeanut/"
        #interp_loc += "saved_models/2021_Wollaeger_TorusSphericalWind1/"
        #interp_loc += "saved_models/2021_Wollaeger_TorusPeanutWind1/"
        
        self.angles = [0, 30, 45, 60, 75, 90]

        interpolator_suffixes = ["%03d" % i for i in range(264)]

        self.t_interp_full = np.logspace(np.log10(0.125), np.log10(37.239195485411194), 264)

        self.interpolators = {angle:[] for angle in self.angles}

        ### rather than preload all the interpolators, just store their string names and load them on the fly
        for i, suffix in enumerate(interpolator_suffixes):
            for angle in self.angles:
                if angle == 0: angle = '00'
                self.interpolators[int(angle)].append(interp_loc + "theta" + str(angle) + "deg/t_" + "{:1.3f}".format(self.t_interp_full[int(suffix)]) + "_days/model")
        
        self.lmbda_dict = { # dictionary of wavelengths corresponding to bands
                "g":477.56,
                "r":612.95,
                "i":748.46,
                "z":865.78,
                "y":960.31,
                "J":1235.0,
                "H":1662.0,
                "K":2159.0
        }

        self.params_array = None # internal storage of parameter array
        self.theta = None # internal storage of theta specifically (for convenience)
        self.distance_Mpc = None
    
    def set_params(self, params, t_bounds):
        ### params should be a dictionary mapping parameter names to either single floats or 1d arrays.
        ### if it's a float, convert it to an array
        if isinstance(params["mej_dyn"], float):
            self.params_array = np.empty((1, 5))
            self.theta = np.array([params["theta"]])
        else:
            self.params_array = np.empty((params["mej_dyn"].size, 5))
            self.theta = params["theta"]

        if not(isinstance(self.theta, np.ndarray)):
            print("Theta argument: ", self.theta)
            raise Exception(" Error: self.theta is not being passed with sensible units, please check it !")

        ### make a dictionary mapping angular bins - e.g. (0, 30) - to arrays of integers.
        ### these arrays give the indices of self.params_array with theta values inside that angular bin.
        self.index_dict = {}
        for angle_index in range(len(self.angles) - 1):
            theta_lower = self.angles[angle_index]
            theta_upper = self.angles[angle_index + 1]
            self.index_dict[(theta_lower, theta_upper)] = np.where((float(theta_lower) <= self.theta) & (self.theta < float(theta_upper)))[0]
        
        ### now populate the parameter array
        self.params_array[:,0] = params["mej_dyn"]
        self.params_array[:,1] = params["vej_dyn"]
        self.params_array[:,2] = params["mej_wind"]
        self.params_array[:,3] = params["vej_wind"]
        if 'distance' in params:
            self.distance_Mpc = params["distance"]
        else:
            self.distance_Mpc = None
    
    def evaluate(self, tvec_days, band):
        print(band + " band:")
        self.params_array[:,4] = self.lmbda_dict[band]

        ### find out which interpolators we actually need to use
        ind_list = [] # list of interpolator indices (i.e. an integer 0, 1, ..., 190) that are used
        t_interp = [] # list of times corresponding to these interpolators
        for t in tvec_days:
            for i in range(self.t_interp_full.size - 1):
                if self.t_interp_full[i] <= t < self.t_interp_full[i + 1]:
                    if i not in ind_list:
                        t_interp.append(self.t_interp_full[i])
                        ind_list.append(i)
                    if i + 1 not in ind_list:
                        t_interp.append(self.t_interp_full[i + 1])
                        ind_list.append(i + 1)

        t_interp = np.array(t_interp)

        ### 2d arrays to hold the interpolator values.
        ### each row is one light curve corresponding to the parameter values in that row of self.params_array.
        ### each column is a time value corresponding to t_interp
        mags_interp = np.empty((self.params_array.shape[0], t_interp.size))
        mags_err_interp = np.empty((self.params_array.shape[0], t_interp.size))

        for lc_index in range(t_interp.size):
            #if lc_index == 0 or (lc_index + 1) % 5 == 0:
            print("  evaluating time step {} of {}".format(lc_index + 1, t_interp.size))
            interp_index = ind_list[lc_index]
            
            ### iterate over angular bins
            for angle_index in range(len(self.angles) - 1):
                theta_lower = self.angles[angle_index]
                theta_upper = self.angles[angle_index + 1]
                delta_theta = float(theta_upper) - float(theta_lower)
                param_indices = self.index_dict[(theta_lower, theta_upper)] # indices of self.params_array corresponding to this angular bin
                if param_indices.size == 0: # skip loading and evaluating the interpolators if we have no points to evaluate
                    continue
                interp_lower = _load_gp(self.interpolators[theta_lower][interp_index])
                interp_upper = _load_gp(self.interpolators[theta_upper][interp_index])
                
                ### evaluate the interpolator at this time step for the upper and lower angles
                mags_lower, mags_err_lower = _model_predict(interp_lower, self.params_array[param_indices])#, fix_log=((interp_index >= 200) and theta_lower in [30, 45, 60]))
                mags_upper, mags_err_upper = _model_predict(interp_upper, self.params_array[param_indices])#, fix_log=((interp_index >= 200) and theta_upper in [30, 45, 60]))
                #if np.any(np.abs(mags_lower) > 100):
                #    print(theta_lower, mags_lower)
                #if np.any(np.abs(mags_upper) > 100):
                #    print(theta_upper, mags_upper)

                ### insert these values in the column of mags_interp corresponding to this time step and the row(s) corresponding to this angular bin
                mags_interp[:,lc_index][param_indices] = ((theta_upper - self.theta[param_indices]) * mags_lower
                        + (self.theta[param_indices] - theta_lower) * mags_upper) / delta_theta
                mags_err_interp[:,lc_index][param_indices] = ((theta_upper - self.theta[param_indices]) * mags_err_lower
                        + (self.theta[param_indices] - theta_lower) * mags_err_upper) / delta_theta
                
        ### now we need to construct the light curves at the user-requested times
        ### start by creating empty arrays with rows corresponding to rows of self.params_array and columns corresponding to the user-requested times
        mags_out = np.empty((self.params_array.shape[0], tvec_days.size))
        mags_err_out = np.empty((self.params_array.shape[0], tvec_days.size))

        if not(self.distance_Mpc is None):
            dist_correct_mag = 5*np.log10(self.distance_Mpc*1e6)-5 # distance in Mpc, factor of 10 pc taken care of with "-5" term
        else: dist_correct_mag=np.zeros(self.params_array.shape[0])
        
        ### iterate over light curves (or parameter combinations, depending on how you look at it)
        for i in range(self.params_array.shape[0]):
            ### make a 1d interpolator for magnitudes and another for errors
            mags_interpolator = interp1d(t_interp, mags_interp[i], fill_value="extrapolate")
            mags_err_interpolator = interp1d(t_interp, mags_err_interp[i], fill_value="extrapolate")
            ### evaluate
            mags_out[i] = mags_interpolator(tvec_days) + dist_correct_mag[i]
            mags_err_out[i] = mags_err_interpolator(tvec_days)
        
        if self.params_array.shape[0] == 1:
            ### if the model is being used in non-vectorized form, return 1d arrays
            return mags_out.flatten(), mags_err_out.flatten()
        return mags_out, mags_err_out

class kn_interp_angle_no_mej_dyn(kn_interp_angle):
    def __init__(self):
        kn_interp_angle.__init__(self)

    def set_params(self, params, t_bounds):
        ### params should be a dictionary mapping parameter names to either single floats or 1d arrays.
        ### if it's a float, convert it to an array
        print('I am setting parameters')
        if isinstance(params["mej_dyn"], float):
            self.params_array = np.empty((1, 5))
            self.theta = np.array([params["theta"]])
        else:
            self.params_array = np.empty((params["mej_dyn"].size, 5))
            self.theta = params["theta"]

        ### make a dictionary mapping angular bins - e.g. (0, 30) - to arrays of integers.
        ### these arrays give the indices of self.params_array with theta values inside that angular bin.
        self.index_dict = {}
        for angle_index in range(len(self.angles) - 1):
            theta_lower = self.angles[angle_index]
            theta_upper = self.angles[angle_index + 1]
            self.index_dict[(theta_lower, theta_upper)] = np.where((theta_lower <= self.theta) & (self.theta < theta_upper))[0]
        
        ### now populate the parameter array
        #self.params_array[:,0] = params["mej_dyn"]
        #self.params_array[:,0] = params["mej_wind"]/2.81 # wind2
        self.params_array[:,0] = params["mej_wind"]/13.90 # wind1
        self.params_array[:,1] = params["vej_dyn"]
        self.params_array[:,2] = params["mej_wind"]
        self.params_array[:,3] = params["vej_wind"]
        print(self.params_array.shape)
