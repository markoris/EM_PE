# -*- coding: utf-8 -*-

from __future__ import print_function
import numpy as np
import argparse
import sys

#try:
#    import matplotlib.pyplot as plt
#except:
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from em_pe.models import model_dict

def _parse_command_line_args():
    '''
    Parses and returns the command line arguments.
    '''
    parser = argparse.ArgumentParser(description='Generate lightcurve plot from data or models')
    parser.add_argument('--posterior-samples', help='Posterior sample file to plot')
    parser.add_argument('--out', help='Filename to save plot to')
    parser.add_argument('--m', help='Model name')
    parser.add_argument('--tmin', type=float, help='Minimum time')
    parser.add_argument('--tmax', type=float, help='Maximum time')
    parser.add_argument('--lc-file', action='append', help='Actual lightcurve data to plot (in same order as posterior sample files)')
    parser.add_argument('--b', action='append', help='Bands to plot (in same order as posterior sample files)')
    parser.add_argument('--fixed-param', action='append', nargs=2, help='Fixed parameters (i.e. parameters without posterior samples)')
    parser.add_argument('--log-time', action='store_true', help='Use a log scale for time axis')
    parser.add_argument('--font-size', type=float, help="Font size for plotting")
    parser.add_argument('--late-start', action='store_true', help='Start at 0.125 or 0.5 days for light curve plotting.')
    parser.add_argument('--morph-comp', type=str, help='Morphology/composition of model')
    return parser.parse_args()

def generate_lc_plot(out, b, tmin, tmax, m=None, sample_file=None, lc_file=None, fixed_params=None, log_time=False, font_size=16, late_start=False, morph_comp="TP2"):
    '''
    Generate a lightcurve plot

    Parameters
    ----------
    sample_file : str
        Posterior sample file
    out : str
        Filename to save plot to
    m : str
        Name of model to use
    tmin : float
        Start time
    tmax : float
        End time
    b : list
        List of data bands
    lc_file : list
        List of lightcurve data files
    fixed_params : list
        List of [param_name, value] pairs
    '''
    if m is None and lc_file is None:
        raise RuntimeError("Nothing to plot.")
    elif m is not None and sample_file is None and fixed_params is None:
        raise RuntimeError("No samples supplied for model evaluation.")
    ### colors to use for each band
    colors = {"K":"darkred", "H":"red", "J":"orange", "y":"gold", "z":"greenyellow", "i":"green", "r":"lime", "g":"cyan", "u":"blue"}
    offsets = {"K":0, "H":1, "J":2, "y":3, "z":4, "i":5, "r":6, "g":7}
    plt.figure(figsize=(12, 8))
    if m is not None:
        #model = model_dict[m](self)
        if m == "kn_interp_angle":
            model = model_dict[m](morph_comp)
        else:
            model = model_dict[m](self)
        with open(sample_file) as f:
            ### the "header" contains the column names
            header = f.readline().strip().split(' ')
        samples = np.loadtxt(sample_file)
        header = header[1:]
        lnL = samples[:,0]
        #best_params = samples[np.argmax(lnL)][3:]
        p = samples[:,1]
        p_s = samples[:,2]
        ### shift all the lnL values up so that we don't have rounding issues
        lnL -= np.max(lnL)
        L = np.exp(lnL)
        ### calculate weights
        weights = L * p / p_s
        best_params = np.array([_quantile(samples[:,i], [0.5], weights=(weights / np.sum(weights)))[0] for i in range(3, len(header))])
        _, c = samples.shape
        num_samples = 100
        random_param_ind = np.random.choice(np.arange(weights.size), p=(weights / np.sum(weights)), size=num_samples)
        param_array = samples[:,3:][random_param_ind]
        #for col in range(3, c):
        #    p = header[col]
        #    values = samples[:,col]
        #    ### get intervals of parameters
        #    lower = _quantile(values, 0.05, weights)
        #    upper = _quantile(values, 0.95, weights)
        #    ### randomly sample some points in this range
        #    param_array[:,col - 3] = np.random.uniform(lower, upper, num_samples)
        n_pts = 25
        t = np.logspace(np.log10(tmin), np.log10(tmax), n_pts)
        param_names = header[3:]
        param_array[0] = best_params
        #best_params = dict(zip(param_names, best_params))
        #if fixed_params is not None:
        #    for [name, val] in fixed_params:
        #        best_params[name] = val
        for band in b:
            #model.set_params(best_params, [tmin, tmax])
            #best_lc = model.evaluate(t, band)[0] + 5.0 * (np.log10(best_params['dist'] * 1.0e6) - 1.0)
            if band in colors:
                color = colors[band]
            else:
                print("No matching color for band", band)
                color=None
            plot_ranges = True
            if plot_ranges:
                if model.vectorized:
                    params = dict(zip(param_names, [param_array[:,i] for i in range(len(param_names))]))
                    if fixed_params is not None:
                        for [name, val] in fixed_params:
                            params[name] = np.ones(num_samples) * val
                    model.set_params(params, [tmin, tmax])
                    lc_array, lc_err_array = model.evaluate(t, band)
                    if m != "kn_interp_angle":
                        for i in range(num_samples):
                            lc_array[i] += 5.0 * (np.log10(params["distance"][i] * 1.0e6) - 1.0)
                else:
                    lc_array = np.empty((num_samples, n_pts))
                    lc_err_array = np.empty((num_samples, n_pts))
                    for row in range(num_samples):
                        params = dict(zip(param_names, param_array[row]))
                        if fixed_params is not None:
                            for [name, val] in fixed_params:
                                params[name] = val
                        model.set_params(params, [tmin, tmax])
                        dist = params['distance']
                        lc_array[row], lc_err_array[row] = model.evaluate(t, band)
                        if m != "kn_interp_angle":
                            lc_array[row] += 5.0 * (np.log10(dist * 1.0e6) - 1.0)
                lc_array += offsets[band]
                #min_lc = np.amin(lc_array, axis=0)
                #max_lc = np.amax(lc_array, axis=0)
                best_lc = lc_array[0]
                #plt.plot(t, min_lc, color=color, label=band)
                #plt.plot(t, max_lc, color=color)
                plt.plot(t, best_lc, color=color, label=band + " + " + str(offsets[band]))
                min_lc = np.quantile(lc_array, 0.05, axis=0)
                max_lc = np.quantile(lc_array, 0.95, axis=0)
                plt.fill_between(t, min_lc, max_lc, color=color, alpha=0.1)
    if lc_file is not None:
        minval = np.inf
        maxval = -np.inf
        for fname in lc_file:
            band = fname.split(".")[0]
            if band in colors:
                color = colors[band]
            else:
                print("No matching color for band", band)
                color=None
            lc = np.loadtxt(fname)
            if lc.ndim == 1:
                t = lc[0]
                err = lc[3]
                lc = lc[2] + offsets[band]
            else: 
                t = lc[:,0]
                err = lc[:,3]
                lc = lc[:,2] + offsets[band]
            minval = min(minval, np.min(lc))
            maxval = max(maxval, np.max(lc))
            plt.errorbar(t, lc, yerr=err, fmt="none", capsize=2, color=color)
        maxval += 2.0
        minval -= 2.0
        plt.ylim(minval, maxval)
    if lc_file is not None:
        plt.ylim(maxval, minval)
    else:
        plt.gca().invert_yaxis()
    if log_time:
        plt.xscale('log')
    if late_start:
        ticks = [x for x in [0.5, 1, 2, 4, 8, 16, 32] if x <= tmax]
    else:
        ticks = [x for x in [0.125, 0.5, 1, 2, 4, 8, 16, 32] if x <= tmax]
    labels = [str(x) for x in ticks]
    plt.gca().set_xticks(ticks)
    plt.gca().set_xticklabels(labels)
    if font_size==None: font_size=16
    plt.gca().tick_params(labelsize=font_size)
    plt.ylabel('$m_{AB}$', fontsize=font_size)
    plt.legend(prop={"size":0.75*font_size}, ncol=2, framealpha=0)
    plt.xlabel('Time (days)', fontsize=font_size)
    plt.tight_layout()
    plt.savefig(out)

def _quantile(x, q, weights=None):
    '''
    Note
    ----
    This code is copied from `corner.py <https://github.com/dfm/corner.py/blob/master/corner/corner.py>`_

    Compute sample quantiles with support for weighted samples.
    Note
    ----
    When ``weights`` is ``None``, this method simply calls numpy's percentile
    function with the values of ``q`` multiplied by 100.

    Parameters
    ----------
    generate_lc_plot(samples, out, m, tmin, tmax, b, lc_file, fixed_params)
    x : array_like[nsamples,]
       The samples.
    q : array_like[nquantiles,]
       The list of quantiles to compute. These should all be in the range
       ``[0, 1]``.
    weights : Optional[array_like[nsamples,]]
        An optional weight corresponding to each sample.

    Returns
    -------
    quantiles : array_like[nquantiles,]
        The sample quantiles computed at ``q``.
    Raises
    ------
    ValueError
        For invalid quantiles; ``q`` not in ``[0, 1]`` or dimension mismatch
        between ``x`` and ``weights``.
    '''
    x = np.atleast_1d(x)
    q = np.atleast_1d(q)

    if np.any(q < 0.0) or np.any(q > 1.0):
        raise ValueError("Quantiles must be between 0 and 1")

    if weights is None:
        return np.percentile(x, list(100.0 * q))
    else:
        weights = np.atleast_1d(weights)
        if len(x) != len(weights):
            raise ValueError("Dimension mismatch: len(weights) != len(x)")
        idx = np.argsort(x)
        sw = weights[idx]
        cdf = np.cumsum(sw)[:-1]
        cdf /= cdf[-1]
        cdf = np.append(0, cdf)
    return np.interp(q, cdf, x[idx]).tolist()

def main():
    args = _parse_command_line_args()
    sample_file = args.posterior_samples
    out = args.out
    m = args.m
    tmin = args.tmin
    tmax = args.tmax
    b = args.b
    lc_file = args.lc_file
    fixed_params = args.fixed_param
    font_size = args.font_size
    late_start = args.late_start
    morph_comp = args.morph_comp
    if fixed_params is not None:
        for i in range(len(fixed_params)):
            fixed_params[i][1] = float(fixed_params[i][1])
    log_time = args.log_time
    generate_lc_plot(out, b, tmin, tmax, m=m, sample_file=sample_file, lc_file=lc_file, fixed_params=fixed_params, log_time=log_time, font_size=font_size, late_start=late_start, morph_comp=morph_comp)

if __name__ == '__main__':
    main()
