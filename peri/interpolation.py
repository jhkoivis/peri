import numpy as np

class BarnesInterpolation1D(object):
    def __init__(self, x, d, filter_size=None, iterations=4, clip=False,
            clipsize=3, damp=0.95):
        """
        A class for 1-d barnes interpolation. Give data points d at locations x.

        See [1]_, equations 1-7 for implementation.

        Parameters
        ----------
        x : ndarray, 1-dimensional
            input positions, x values for data points

        d : ndarray, 1-dimensional
            input values, y values for data points

        filter_size : float, optional.
            control parameter for weight function (sigma), should be the
            average data spacing. Defaults to the average distance for
            sorted ``x``.

        iterations : integer, optional
            how many iterations to perform. only two needed with a high damping
            Defaults to 4

        clip : boolean, optional
            whether to clip the number of data points used by the filtersize
            Default is False

        clipsize : float, optional
            Total clipsize is determined by clipsize * filter_size
            Default is 3

        damp : float, optional
            the damping parameter used in accelerating convergence. Default
            is 0.95

        References
        ----------
        .. [1] S. E. Koch, M. DesJardins, P. J. Kocin, J. Climate Appl.
                Meteor. 22 1487-1503 (1983)
        """
        self.x = x
        self.d = d
        self.damp = damp
        self.clip = clip
        self.iterations = iterations

        if filter_size is None:
            self.filter_size = self._default_filter_size()
        else:
            self.filter_size = filter_size

        self.clipsize = clipsize * self.filter_size

    def _default_filter_size(self):
        return (self.x[1:] - self.x[:-1]).mean()/2

    def _weight(self, rsq, size=None):
        """weighting function for Barnes"""
        size = size or self.filter_size

        o = np.exp(-rsq / (2*size**2))
        o = o * (not self.clip or (self.clip and (rsq < self.clipsize**2)))
        return o

    def _outer(self, a, b):
        """Pairwise distance between each point in `a` and each point in `b`"""
        return (a[:,None] - b[None,:])**2

    def __call__(self, rvecs):
        """
        Get the values interpolated at positions rvecs
        """
        g = self.filter_size

        dist0 = self._outer(self.x, self.x)
        dist1 = self._outer(rvecs, self.x)

        tmp = self._weight(dist0, g).dot(self.d)
        out = self._weight(dist1, g).dot(self.d)

        for i in xrange(self.iterations):
            out = out + self._weight(dist1, g).dot(self.d - tmp)
            tmp = tmp + self._weight(dist0, g).dot(self.d - tmp)
            g *= self.damp
        return out

class BarnesInterpolationND(BarnesInterpolation1D):
    """Barnes interpolant in N dimensions"""
    def __init__(self, *args, **kwargs):
        """
        A class for barnes interpolation in N dimensions.

        Parameters
        ----------
        x : ndarray, 2-dimensional
            input positions, x values for data points. x[i] is the ith position

        d : ndarray, 1-dimensional
            input values, y values for data points. Same number of points as
            x has positions.

        See Also
        --------
        BarnesInterpolation1D
        """
        super(BarnesInterpolationND, self).__init__(*args, **kwargs)

    def _outer(self, a, b):
        """Pairwise distance between each point in `a` and each point in `b`"""
        sq = lambda x: (x*x)
        matrix = np.sum(map(lambda a,b: sq(a[:,None] - b[None,:]),
                a.T, b.T), axis=0)
        return matrix

    def _default_filter_size(self):
        dist = lambda x: np.sqrt(np.sum(x*x, axis=1))
        return dist(self.x[1:] - self.x[:-1]).mean()/2

class ChebyshevInterpolation1D(object):
    def __init__(self, func, args=(), window=(0.,1.), degree=3, evalpts=4):
        """
        A 1D Chebyshev approximation / interpolation for an ND function, approximating
        (N-1)D in in the last dimension. 

        Parameters
        ----------
        func : callable
            A function that takes scalar arguments (1D) and returns a N
            dimensional array corresponding to that scalar. Make it such that,
            for an array x, f(x)[.....,a] corresponds to f(x[a])

        args : tuple [optional]
            extra arguments to pass to func

        window : tuple (length 2)
            The bounds of the function over which we desire the interpolation

        degree : integer
            Degree of the Chebyshev interpolating polynomial

        evalpts : integer
            Number of Chebyshev points to evaluate the function at
        """
        self.args = args
        self.func = func
        self.window = window
        self.set_order(evalpts, degree)
        
    def _x2c(self, x):
        """ Convert windowdow coordinates to cheb coordinates [-1,1] """
        return (2*x-self.window[1]-self.window[0])/(self.window[1]-self.window[0])

    def _c2x(self, c):
        """ Convert cheb coordinates to windowdow coordinates """
        return 0.5*(self.window[0]+self.window[1]+c*(self.window[1]-self.window[0]))
    
    def _construct_coefficients(self):
        """
        Calculate the coefficients based on the func, degree, and interpolating points.
        _coeffs is a [order, N,M,....] array

        Notes 
        -----
        Moved the -c0 to the coefficients defintion
        app -= 0.5 * self._coeffs[0] -- moving this to the coefficients
        """
        coeffs = [0]*self.degree
        
        N = float(self.evalpts)
        
        lvals = np.arange(self.evalpts).astype('float')
        xpts = self._c2x(np.cos(np.pi*(lvals + 0.5)/N))
        fpts = np.rollaxis(self.func(xpts, *self.args), -1)
        
        for a in xrange(self.degree):
            inner = [
                fpts[b] * np.cos(np.pi*a*(lvals[b]+0.5)/N)
                for b in xrange(self.evalpts)
            ] 
            coeffs[a] = 2.0/N * np.sum(inner, axis=0)
            
        coeffs[0] *= 0.5
        self._coeffs = np.array(coeffs)

    def set_order(self, evalpts, degree):
        if evalpts < degree:
            raise ValueError("Number of Chebyshev points must be > degree")
        
        self.evalpts = evalpts
        self.degree = degree
        
        self._construct_coefficients()

    @property
    def coefficients(self):
        return self._coeffs.copy()

    def tk(self, k, x):
        """
        Evaluates an individual Chebyshev polynomial `k` in coordinate space
        with proper transformation given the window
        """
        weights = np.diag(np.ones(k+1))[k]
        return np.polynomial.chebyshev.chebval(self._x2c(x), weights)

    def __call__(self, x):
        """
        Approximates `func` at the coordinates x, which must be in the window.

        .. math::
            f(x) = \sum_{k=0}^{N-1} c_k T_k(x) - co/2

        Output is in the format [A,...,x]
        """
        return np.polynomial.chebyshev.chebval(self._x2c(x), self._coeffs, tensor=True)
