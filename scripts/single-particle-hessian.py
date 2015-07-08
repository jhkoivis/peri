import matplotlib as mpl
mpl.use('Agg')
import numpy as np
import pylab as pl

from cbamf import runner
from cbamf.test import init
from cbamf.viz import plots

s = init.create_single_particle_state(imsize=64, radius=5.0, sigma=0.05,
        psf=(2.0, 4.0), seed=10)

hess = s.hessloglikelihood()

pl.figure()
pl.imshow(np.log10(np.abs(hess)))
pl.title("Log Hessian matrix")
pl.colorbar()
pl.show()

#h, ll = runner.do_samples(s, 30, 5)
#plots.summary_plot(s, h, truestate=strue)
