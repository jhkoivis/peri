import os,sys, time, warnings
import numpy as np
from numpy.random import randint
from scipy.optimize import newton, minimize_scalar
from cbamf.util import Tile

"""
Algorithm is:
1. Evaluate J_ia = df(xi,mu)/dmu_a
2. Solve the for delta:
    (J^T*J + l*Diag(J^T*J))*delta = J^T(y-f(xi,mu))     (1)
3. Update mu -> mu + delta

To solve eq. (1), we need to:
1. Construct the matrix JTJ = J^T*J
2. Construct the matrix A=JTJ + l*Diag(JTJ)
3. Construct err= y-f(x,beta)
4. np.linalg.solve(A,err)

My only change to this is, instead of calculating J_ia, we calculate
J_ia for a small subset (say 1%) of the pixels in the image randomly selected,
rather than for all the pixels

You need a way to deal with flat / near flat components in the JTJ. 
If the eigenvalue is 0 then the matrix inverse is super ill-conditioned
and you get crap for the suggested step. 

"""

def calculate_J_approx(s, blocks, inds, **kwargs):
    """
    Calculates an approximage J for levenberg-marquardt
    Inputs:
        - s: state to minimize
        - blocks: List of the blocks to optimize over
        - inds: 3-element list; the indices of the _inner_ image to compare
            with. Recommended to be selected randomly. 
    """
    to_return = []
    for b in blocks:
        a_der = eval_deriv(s, b, **kwargs)
        to_return.append(a_der[inds[0], inds[1], inds[2]].ravel().copy())
    return np.array(to_return)
    
def calculate_J_exact(s, blocks, **kwargs): #delete me
    """
    Calculates an exact J for levenberg-marquardt
    Inputs:
        - s: state to minimize
        - blocks: List of the blocks to optimize over
    """
    to_return = []
    for b in blocks:
        a_der = eval_deriv(s, b, **kwargs)
        to_return.append(a_der.ravel())
    return np.array(to_return)

def calculate_err_approx(s, inds):
    return s.get_difference_image()[inds[0], inds[1], inds[2]].ravel().copy()
    
def eval_deriv(s, block, dl=1e-8, be_nice=False, threept=False, **kwargs):
    """
    Using a centered difference / 3pt stencil approximation:
    """
    if not threept:
        i0 = s.get_difference_image().copy()
    
    p0 = s.state[block]
    s.update(block, p0+dl)
    i1 = s.get_difference_image().copy()
    if threept:
        s.update(block, p0-dl)
        i2 = s.get_difference_image().copy()
        deriv = 0.5*(i1-i2)/dl
    else:
        deriv = (i1-i0)/dl
    if be_nice:
       s.update(block, p0) 
    return deriv
    
def calculate_JTJ_grad_approx(s, blocks, num_inds=1000, **kwargs):
    if num_inds < s.image[s.inner].size:
        inds = [randint(v, size=num_inds) for v in s.image[s.inner].shape]
    else:
        inds = [slice(0,None), slice(0,None), slice(0,None)]
    J = calculate_J_approx(s, blocks, inds, **kwargs)
    JTJ = np.dot(J, J.T)
    err = calculate_err_approx(s, inds)
    return JTJ, np.dot(J,err)
    
def get_rand_Japprox(s, blocks, num_inds=1000, keep_time=True, **kwargs):
    """
    """
    if keep_time:
        start_time = time.time()
    #You need a better way to select indices to minimize over.
    tot_pix = s.image[s.inner].size
    if num_inds < tot_pix:
        # inds = [randint(v, size=num_inds) for v in s.image[s.inner].shape]
        inds = list(np.unravel_index(np.random.choice(tot_pix, size=num_inds, 
                replace=False), s.image[s.inner].shape))
    else:
        inds = [slice(0,None), slice(0,None), slice(0,None)]
    J = calculate_J_approx(s, blocks, inds, **kwargs)
    if keep_time:
        print 'JTJ:\t%f' % (time.time()-start_time)
    return J, inds
        
def j_to_jtj(J):
    return np.dot(J, J.T)

def calc_im_grad(s, J, inds):
    err = calculate_err_approx(s, inds)
    return np.dot(J, err)

def find_LM_updates(JTJ, grad, damp=1.0, min_eigval=1e-12, quiet=True, **kwargs):
    diag = np.diagflat(np.diag(JTJ))
    
    A0 = JTJ + damp*diag
    delta0, res, rank, s = np.linalg.lstsq(A0, -grad, rcond=min_eigval)
    if not quiet:
        print '%d degenerate of %d total directions' % (delta0.size-rank, delta0.size)
    
    return delta0
    
def update_state_global(s, block, data, keep_time=False, **kwargs):
    """
    """
    #We need to update:
    #obj, psf, ilm, bkg, off, slab, zscale, rscale, sigma
    if keep_time:
        start_time = time.time()
    
    old_state = s.state
    new_state = old_state.copy(); new_state[block] = data.copy()

    updated = {'pos', 'rad', 'typ', 'psf', 'ilm', 'bkg', 'off', 'slab', \
        'zscale', 'sigma', 'rscale'}
    if updated != set(s.param_order):
        raise RuntimeError('This state has parameters that arent supported!')
    
    #Since zscale affects obj, it needs to be first:
    #zscale:
    bz = s.create_block('zscale')
    if (bz & block).sum() > 0:
        new_zscale = new_state[bz].copy()
        s.update(bz, new_zscale)
    
    #obj:
    #pos:
    bpos = s.create_block('pos')
    if (bpos & block).sum() > 0:
        new_pos_params = new_state[bpos].copy().reshape(-1,3)
        s.obj.pos = new_pos_params
    #rad:
    brad = s.create_block('rad')
    if (brad & block).sum() > 0:
        new_rad_params = new_state[brad].copy()
        s.obj.rad = new_rad_params
    #typ:
    btyp = s.create_block('typ')
    if (btyp & block).sum() > 0:
        new_typ_params = new_state[btyp].copy()
        s.obj.typ = new_typ_params
    if np.any(bpos | brad | btyp):
        s.obj.initialize(s.zscale)
    
    #psf:
    bp = s.create_block('psf')
    if (bp & block).sum() > 0:
        new_psf_params = new_state[bp].copy()
        s.psf.update(new_psf_params)
        
    #ilm:
    bi = s.create_block('ilm')
    if (bi & block).sum() > 0:
        new_ilm_params = new_state[bi].copy()
        s.ilm.update(s.ilm.block, new_ilm_params)
        
    #bkg:
    bb = s.create_block('bkg')
    if (bb & block).sum() > 0:
        new_bkg_params = new_state[bb].copy()
        s.bkg.update(s.bkg.block, new_bkg_params)
    
    #off:
    bo = s.create_block('off')
    if (bo & block).sum() > 0:
        new_off = new_state[bo].copy()
        s.update(bo, new_off)
    
    #slab:
    bs = s.create_block('slab')
    if (bs & block).sum() > 0:
        new_slab_params = new_state[bs].copy()
        s.slab.update(new_slab_params)
        
    #rscale:
    brscl = s.create_block('rscale')
    if (brscl & block).sum() > 0:
        new_rscale = new_state[brscl].copy()
        s.update(brscl, new_rscale)
    
    #sigma:
    bsig = s.create_block('sigma')
    if (bsig & block).sum() > 0:
        new_sig = new_state[bsig].copy()
        s.update(bsig, new_sig)
    
    #Now we need to reset the state and return:
    s._build_state()
    s._update_global()
    if keep_time:
        print 'update_state_global:\t%f' % (time.time()-start_time) 

def get_err(s):
    d = s.get_difference_image()
    return np.sum(d*d)

def get_num_px_jtj(s, nparams, decimate=400, max_mem=2e9, min_redundant=20, **kwargs):
    #1. Max for a given max_mem:
    px_mem = int( max_mem /8/ nparams) #1 float = 8 bytes
    #2. # for a given
    px_red = min_redundant*nparams
    #3. And # desired for decimation
    px_dec = s.image[s.inner].size/decimate
    
    if px_red > px_mem:
        raise RuntimeError('Insufficient max_mem for desired redundancy.')
    num_px = np.clip(px_dec, px_red, px_mem)
    return num_px
    
def do_levmarq(s, block, damp=0.1, ddamp=0.1, num_iter=5, do_run=True, \
         run_length=5, **kwargs):
    """
    Runs Levenberg-Marquardt minimization on a cbamf state, based on a
    random approximant of J. Doesn't return anything, only updates the state. 
    Parameters:
    -----------
    s : State
        The cbamf state to optimize. 
    block: Boolean numpy.array
        The desired blocks of the state s to minimize over. Do NOT explode it. 
    damp: Float scalar, >=0. 
        The damping parameter in the Levenberg-Marquardt optimization.
        Big damping means gradient descent with a small step, damp=0
        means Hessian inversion. Default is 0.1. 
    ddamp: Float scalar, >0. 
        Multiplicative value to update damp by. Internally decides when to
        update and when to use damp or 1/damp. Default is 0.1. 
    num_iter: Int. 
        Number of Levenberg-Marquardt iterations before returning. 
    do_run: Bool
        Set to True to attempt multiple minimzations by using the old
        (expensive) JTJ to re-calculate a next step. Default is True. 
    run_length: Int. 
        Maximum number of attempted iterations with a fixed JTJ. Only 
        matters if do_run=True. Default is 5. 
    decimate: Float scalar, >1
        The desired amount to decimate the pixels by for a random image (e.g.
        decimate of 10 takes  1/10 of the pixels). However, the actual amount
        of pixels is determined by max_mem and min_redundant as well. If < 1, 
        the attempts to use all the pixels in the image. Default is 400. 
    max_mem: Float scalar. 
        The maximum memory (in bytes) that J should occupy. Default is 2GB. 
    min_redundant: Float scalar. 
        Enforces a minimum amount of pixels to include in J, such that the 
        min # of pixels is at least min_redundant * number of parameters. 
        If max_mem and min_redundant result in an incompatible size an
        error is raised. Default is 20. 
    min_eigval: Float scalar, <<1. 
        The minimum eigenvalue to use in inverting the JTJ matrix, to avoid
        degeneracies in the parameter space (i.e. 'rcond' in np.linalg.lstsq).
        Default is 1e-12. 
    keep_time: Bool
        Set to True to print messages about how long each step of the
        algorithm took. Default is False. 
    be_nice: Bool
        If True, spends extra updates placing the parameters back to
        their original values after evaluating the derivatives. Default
        is False, i.e. plays fast (2x with threept=False) and dangerous. 
    dl: Float scalar.
        The amount to update parameters by when evaluating derivatives. 
        Default is 1e-8, which is fine for everything but rscale. 
    threept: Bool
        Set to True to use a 3-point stencil instead of a 2-point. More 
        accurate but 20% slower. Default is False. 
    
    See Also
    --------
    do_levmarq_particles: Exact (not random-block) Levenberg-Marquardt 
        specially designed for optimizing particle positions. 
    do_levmarq_all_particle_groups: Wrapper for do_levmarq_particles 
        which blocks particles by distance and iterates over all 
        the particles in the state. 
    do_conj_grad_jtj: Conjugate gradient minimization with a random-block
        approximation to J. 
    
    Comments
    --------
    The sampling of pixels for JTJ is stochastic, but the evaluations 
    of the data are not. Since the error is checked against the global 
    image the log-likelihood will never increase during minimization 
    (there are internal checks for this). 
    """
    blocks = s.explode(block)
    #First I find out how many pixels I use:
    num_px = get_num_px_jtj(s, block.sum(), **kwargs)    
    
    def do_internal_run(J, inds, damp):
        """
        Uses the local vars s, damp, run_length, block
        """
        print 'Running....'
        for rn in xrange(run_length):
            new_grad = calc_im_grad(s, J, inds)
            p0 = s.state[block].copy()
            dnew = find_LM_updates(JTJ, new_grad, damp=damp)
            old_err = get_err(s)
            update_state_global(s, block, p0+dnew)
            new_err = get_err(s)
            print '%f\t%f' % (old_err, new_err)
            if new_err > old_err:
                #done running
                update_state_global(s, block, p0)
                break
    
    recalc_J = True
    counter = 0
    # for _ in xrange(num_iter):
    while counter < num_iter:
        p0 = s.state[block].copy()
        err_start = get_err(s)
        
        #1. Get J, JTJ, grad
        if recalc_J:
            J, inds = get_rand_Japprox(s, blocks, num_inds=num_px, **kwargs)
            JTJ = j_to_jtj(J)
            grad = calc_im_grad(s, J, inds) #internal because s gets updated
        
        #2. Calculate and implement first guess for updates
        d0 = find_LM_updates(JTJ, grad, damp=damp)
        d1 = find_LM_updates(JTJ, grad, damp=damp*ddamp)
        update_state_global(s, block, p0+d0)
        err0 = get_err(s)
        update_state_global(s, block, p0+d1)
        err1 = get_err(s)
        
        if np.min([err0, err1]) > err_start: #Bad step...
            print 'Bad step!\t%f\t%f\t%f' % (err_start, err0, err1)
            update_state_global(s, block, p0)
            recalc_J = False
            #Avoiding infinite loops by adding a small amount to counter:
            counter += 0.1 
            if err0 < err1: 
                #d_damp is the wrong "sign", so we invert:
                print 'Inverting ddamp:\t%f\t%f' % (ddamp, 1.0/ddamp)
                ddamp = 1.0/ddamp
            else: 
                #ddamp is the correct sign but damp is too big:
                damp *= (ddamp*ddamp)
        
        else: #at least 1 good step:
            if err0 < err1: #good step and damp, re-update:
                update_state_global(s, block, p0+d0)
                print 'Good step:\t%f\t%f\t%f' % (err_start, err0, err1)
            else: #err1 < err0 < err_start, good step but decrease damp:
                damp *= ddamp
                print 'Changing damping:\t%f\t%f\t%f' % (err_start, err0, err1)
            if do_run:
                do_internal_run(J, inds, damp)
            recalc_J = True
            counter += 1

def do_conj_grad_jtj(s, block, min_eigval=1e-12, num_sweeps=2, **kwargs):
    """
    Runs conjugate-gradient descent on a cbamf state, based on a random
    approximation of the Hessian matrix from JTJ. Does not 
    return anything, only updates the state. 
    Parameters:
    -----------
    s : State
        The cbamf state to optimize. 
    block: Boolean numpy.array
        The desired blocks of the state s to minimize over. Do NOT explode it. 
    min_eigval: Float scalar, <<1. 
        The minimum eigenvalue to use in inverting the JTJ matrix, to avoid
        degeneracies in the parameter space (i.e. 'rcond' in np.linalg.lstsq).
        Default is 1e-12. 
    num_sweeps: Int. 
        Number of sweeps to do over the eigenvectors of the parameter
        block, using the same Hessian approximation. Default is 2. 
    decimate: Float scalar, >1
        The desired amount to decimate the pixels by for a random image (e.g.
        decimate of 10 takes  1/10 of the pixels). However, the actual amount
        of pixels is determined by max_mem and min_redundant as well. If < 1, 
        the attempts to use all the pixels in the image. Default is 400. 
    max_mem: Float scalar. 
        The maximum memory (in bytes) that J should occupy. Default is 2GB. 
    min_redundant: Float scalar. 
        Enforces a minimum amount of pixels to include in J, such that the 
        min # of pixels is at least min_redundant * number of parameters. 
        If max_mem and min_redundant result in an incompatible size an
        error is raised. Default is 20. 
    keep_time: Bool
        Set to True to print messages about how long each step of the
        algorithm took. Default is False. 
    be_nice: Bool. 
        If True, evaluating the derivative doesn't change the state. If 
        False, when the derivative is evaluated the state isn't changed 
        back to its original value, which saves time (33%) but may wreak 
        havoc. Default is True (i.e. slower, no havoc). 
    dl: Float scalar.
        The amount to update parameters by when evaluating derivatives. 
        Default is 2e-5. 
    threept: Bool
        Set to True to use a 3-point stencil instead of a 2-point. More 
        accurate but 20% slower. Default is False. 
    See Also
    --------
    do_levmarq: Levenberg-Marquardt minimization with a random-block
        approximation to J. 
    
    Comments
    --------
    The sampling of pixels for J, JTJ is stochastic, but the evaluations 
    of the data are not. Since the error is checked against the global 
    image the log-likelihood will never increase during minimization 
    (there are internal checks for this). 
    """
    #First find out how many pixels I use:
    num_px = get_num_px_jtj(s, block.sum(), **kwargs)
    blocks = s.explode(block)
    
    #Then I get JTJ etc:
    J, inds = get_rand_Japprox(s, blocks, num_inds=num_px, **kwargs)
    JTJ = j_to_jtj(J)
    grad = calc_im_grad(s, J, inds) #internal because s gets updated
    
    #Now I get the conj. grad. directions:
    evals, evecs = np.linalg.eigh(JTJ)
    
    #And we line minimize over each direction, starting with the smallest
    print 'Starting:\t%f' % get_err(s)
    for n in xrange(num_sweeps):
        for a in xrange(evals.size-1,-1, -1): #high eigenvalues first
            if evals[a] < min_eigval*evals.max():
                print "Degenerate Direction\t%d" % a
                continue #degenerate direction, ignore

            #Picking a good direction/magnitude to move in:
            cur_vec = evecs[:,a] * 0.5*np.dot(-grad, evecs[:,a])/evals[a]
            
            do_line_min(s, block, cur_vec, **kwargs)
            print 'Direction min %d \t%f' % (a, get_err(s))

def do_line_min(s, block, vec, maxiter=10, **kwargs):
    """
    Does a line minimization over the state
    Make vec something that update_state_global(block, p0+vec) is the "correct"
    step size (i.e. takes you near the minimum)
    """
    start_err = get_err(s)
    p0 = s.state[block].copy()
    
    def for_min(x):
        update_state_global(s, block, p0 + x*vec, keep_time=False)
        return get_err(s)
    
    #Need to check for a bracket:
    brk_vals = [for_min(-2.), for_min(2.)]
    cnt_val = for_min(0)
    if cnt_val > np.min(brk_vals):
        #the min is outside the interval, need a new bracket
        run = True
        if brk_vals[0] < brk_vals[1]:
            bracket = [-2,0]
            start = -2.
            old = brk_vals[0]
            while run:
                start *= 3
                new = for_min(start)
                run = new < old; print '....'
            bracket = [start] + bracket
        else:
            bracket = [0,2]
            start = 2
            old = brk_vals[1]
            while run:
                start *= 3
                new = for_min(start)
                run = new < old; print '....'
            bracket.append(start)
    else: #bracket is fine
        bracket = [-2,0,2]
    
    res = minimize_scalar(for_min, bracket=bracket, method='Brent', \
            options={'maxiter':maxiter})
    if res.fun <= start_err:
        _ = for_min(res.x)
    else:
        #wtf
        raise RuntimeError('wtf')
        
#=============================================================================#
#               ~~~~~        Single particle stuff    ~~~~~
#=============================================================================#
def update_one_particle(s, particle, pos, rad, typ=None, relative=False, 
        do_update_tile=True, fix_errors=False, **kwargs):
    """
    Updates a single particle (labeled ind) in the state s. 
    
    Parameters
    -----------
    s : State
        The cbamf state to optimize. 
    particle: 1-element int numpy.ndarray
        Index of the particle to update.
    pos: 3-element numpy.ndarray
        New position of the particle. 
    rad: 1-element numpy.ndarray
        New radius of the particle. 
    typ: 1-element numpy.ndarray.
        New typ of the particle; defaults to the previous typ.
    relative: Bool
        Set to true to make pos, rad updates relative to the previous 
        position (i.e. p1 = p0+pos instead of p1 = pos, etc for rad). 
        Default is False. 
    do_update_tile: Bool
        If False, only updates s.object and not the actual model image. 
        Set to False only if you're going to update manually later. 
        Default is True
    fix_errors: Bool
        Set to True to fix errors for placing particles outside the 
        image or with negative radii (otherwise a ValueError is raised). 
        Default is False
    
    Returns
    --------
    tiles: 3-element list. 
        cbamf.util.Tile's of the region of the image affected by the 
        update. Returns what s._tile_from_particle_change returns 
        (outer, inner, slice)
    """
    if type(particle) != np.ndarray:
        particle = np.array([particle])
    
    prev = s.state.copy()
    p0 = prev[s.b_pos].copy().reshape(-1,3)[particle]
    r0 = prev[s.b_rad][particle]
    t0 = prev[s.b_typ][particle]
    
        
    is_bad_update = lambda p, r: np.any(p < 0) or np.any(p > \
            np.array(s.image.shape)) or np.any(r < 0)
    if fix_errors:
        #Instead of ignoring errors, we modify pos, rad in place
        #so that they are the best possible updates. 
        if relative:
            if is_bad_update(p0+pos, r0+rad):
                pos = np.clip(pos, 1e-6-p0, np.array(s.image.shape)-1e-6-p0)
                rad = np.clip(rad, 1e-6-r0, np.inf)
            pass
        else:
            if is_bad_update(pos, rad):
                pos = np.clip(pos, 1e-6, np.array(s.image.shape)-1e-6)
                rad = np.clip(rad, 1e-6, np.inf)
    
    if typ is None:
        t1 = t0.copy()
    else:
        t1 = typ
    
    if relative:
        p1 = p0 + pos
        r1 = r0 + rad
    else:
        p1 = pos.copy()
        r1 = rad.copy()
        
    if is_bad_update(p1, r1):
        raise ValueError('Particle outside image / negative radius!')
    
    tiles = s._tile_from_particle_change(p0, r0, t0, p1, r1, t1) #312 us
    s.obj.update(particle, p1, r1, t1, s.zscale, difference=s.difference) #4.93 ms
    if do_update_tile:
        s._update_tile(*tiles, difference=s.difference) #66.5 ms
    s._build_state()
    return tiles
    
def eval_one_particle_grad(s, particle, dl=1e-6, threept=False, slicer=None, 
        be_nice=False, **kwargs):
    """
    Evaluates the gradient of the image for 1 particle, for all of its 
    parameters (x,y,z,R). Used for J for LM. 
    
    Parameters
    -----------
    s : State
        The cbamf state to evaluate derivatives on. 
    particle: 1-element int numpy.ndarray
        Index of the particle to evaluate derivatives for.
    slicer: slice
        Slice object of the regions of the image at which to evaluate 
        the derivative. Default is None, which finds the tile of the 
        pixels changed by updating the particle and returns that. 
    dl: Float
        The amount to change values by when evaluating derivatives. 
        Default is 1e-6. 
    threept: Bool
        If True, uses a 3-point finite difference instead of 2-point. 
        Default is False (using two-point for 1 less function call).
    be_nice: Bool
        If True, spends 1x4 extra updates placing the (x,y,z,R) back to
        their original values after evaluating the derivatives. Default
        is False, i.e. plays fast and dangerous. 
    
    Returns
    --------
    grads: numpy.ndarray 
        [4,N] element numpy.ndarray; grads[i,j] is the [x,y,z,R][i] 
        derivative evaluated at the j'th pixel in the affected region. 
    slicer: slice
        The slice containing which points in the image the derivate was 
        evaluated at. If the input parameter slicer is not None, then it
        is the same as the slice passed in. 
    """
    p0 = s.state[s.block_particle_pos(particle)].copy()
        
    grads = []
    if slicer is not None:
        mask = s.image_mask[slicer] == 1
    
    #xyz pos:
    for a in xrange(3):
        if not threept:
            i0 = get_slicered_difference(s, slicer, mask)
        dx = np.zeros(p0.size)
        dx[a] = 1*dl
        tiles = update_one_particle(s, particle, dx, 0, relative=True)
        if slicer == None:
            slicer = tiles[0].slicer
            mask = s.image_mask[slicer] == 1
        
        i1 = get_slicered_difference(s, slicer, mask)
        if threept:
            toss = update_one_particle(s, particle, -2*dx, 0, relative=True)
            #we want to compare the same slice. Also -2 to go backwards
            i2 = get_slicered_difference(s, slicer, mask)
            if be_nice:
                toss = update_one_particle(s, particle, dx, 0, relative=True)
            grads.append((i1-i2)*0.5/dl)
        else:
            if be_nice:
                toss = update_one_particle(s, particle, -dx, 0, relative=True)
            grads.append( (i1-i0)/dl )
    #rad:
    if not threept:
        i0 = get_slicered_difference(s, slicer, mask)
    dr = np.array([dl])
    toss = update_one_particle(s, particle, 0, 1*dr, relative=True)
    i1 = get_slicered_difference(s, slicer, mask)
    if threept:
        toss = update_one_particle(s, particle, 0, -2*dr, relative=True)
        i2 = get_slicered_difference(s, slicer, mask)
        if be_nice:
            toss = update_one_particle(s, particle, 0, dr, relative=True)
        grads.append((i1-i2)*0.5/dl)
    else:
        if be_nice:
            toss = update_one_particle(s, particle, 0, -dr, relative=True)
        grads.append( (i1-i0)/dl )
        
    return np.array(grads), slicer

def eval_many_particle_grad(s, particles, **kwargs):
    """Wrapper for eval_one_particle_grad. Particles is an iterable"""
    grad = []
    for p in particles:
        #throwing out the slicer info right now...
        grad.extend(eval_one_particle_grad(s, p, **kwargs)[0].tolist())
    return np.array(grad)

def find_particles_in_box(s, bounds):
    """
    Finds the particles in a box.
    
    Parameters
    -----------
    s : State
        The cbamf state to find the particle in. 
    bounds: 2-element list-like of lists. 
        bounds[0] is the lower left corner of the box, bounds[1] the upper
        right corner. Each of those are 3-element list-likes of the coords. 
    
    Returns
    --------
    inds: numpy.ndarray
        The indices of the particles in the box. 
    
    """
    is_in_xi = lambda i: (s.obj.pos[:,i] > bounds[0][i]) & (s.obj.pos[:,i] <= bounds[1][i])
    in_region = is_in_xi(0) & is_in_xi(1) & is_in_xi(2)
    return np.nonzero(in_region)[0]

def get_slicered_difference(s, slicer, mask):
    return np.copy((s.image[slicer] - s.get_model_image()[slicer])[mask])

def get_tile_from_multiple_particle_change(s, inds):
    """
    Finds the tile from changing multiple particles by taking the maximum
    enclosing tile
    """
    all_left = []
    all_right = []
    for i in inds:
        p0 = np.array(s.obj.pos[i])
        r0 = np.array([s.obj.rad[i]])
        t0 = np.array([s.obj.typ[i]])
        tile, _, __ = s._tile_from_particle_change(p0, r0, t0, p0, r0, t0)
        all_left.append(tile.l)
        all_right.append(tile.r)
    
    left = np.min(all_left, axis=0)
    right= np.max(all_right,axis=0)
    
    return Tile(left, right=right)

def update_particles(s, particles, params, **kwargs):
    #eval_particle_grad returns parameters in order(p0,r0,p1,r1,p2,r2...)
    #so that determines the order for updating particles:
    all_left = []
    all_right= []
    
    def clean_up_tile(ar, left=True):
        mask = np.array(map( lambda x: x == None, ar))
        if left:
            ar[mask] = 0
        else:
            ar[mask] = np.array(s.image.shape)[mask]
        return ar
    
    #We update the object but only update the field at the end
    for a in xrange(particles.size):
        pos = params[4*a:4*a+3]
        rad = params[4*a+3:4*a+4]
        updated_tiles = update_one_particle(s, particles[a], pos, rad, 
                do_update_tile=False, **kwargs)
        a_left = updated_tiles[0].l.copy()
        a_right= updated_tiles[0].r.copy()
        all_left.append( clean_up_tile(a_left, left=True))
        all_right.append(clean_up_tile(a_right,left=False))
        
    ####FIXME -- needs to be updated for new Tile with reflect-overlap
    #Constructing the tiles to update the field, making sure it's even...:
    if True: #FIXME -- not sure if the tile needs to be even
        left = np.min(all_left, axis=0) - 1
        left += left % 2
        right = np.max(all_right,axis=0) + 1
        right += right % 2
        left = np.clip(left, 0, s.image.shape)
        right= np.clip(right,0, s.image.shape)
    else:
        left = np.min(all_left, axis=0)
        right = np.max(all_right,axis=0)
    outer_tile = Tile(left, right=right)
    #Then I'm basically copying code from s._tile_from_particle_change
    # to get the correct inner, ioslice, which is sloppy so FIXME
    inner_tile = Tile(left+1, right=right-1)
    ioslice = tuple( [np.s_[1:-1] for i in xrange(3)])
    ####
    
    s._update_tile(outer_tile, inner_tile, ioslice, difference=s.difference)
    return outer_tile, inner_tile, ioslice
    
def do_levmarq_particles(s, particles, damp=0.1, ddamp=0.2, num_iter=3,
        do_run=True, run_length=5, **kwargs):
    """
    Runs an exact (i.e. not stochastic number of pixels) Levenberg-Marquardt 
    minimization on a set of particles in a cbamf state. Doesn't return 
    anything, only updates the state. 
    Parameters:
    -----------
    s : State
        The cbamf state to optimize. 
    particles: Int numpy.array
        The desired indices of the particles to minimize over.
    damp: Float scalar, >=0. 
        The damping parameter in the Levenberg-Marquardt optimization.
        Big damping means gradient descent with a small step, damp=0
        means Hessian inversion. Default is 0.1. 
    ddamp: Float scalar, >0. 
        Multiplicative value to update damp by. Internally decides when
        to update and when to use damp or 1/damp. Default is 0.2. 
    num_iter: Int. 
        Number of Levenberg-Marquardt iterations to execute. Default is 3.
    do_run: Bool
        Set to True to attempt multiple minimzations by using the old
        (expensive) JTJ to re-calculate a next step. Default is True. 
    run_length: Int. 
        Maximum number of attempted iterations with a fixed JTJ. Only 
        matters if do_run=True. Default is 5. 
    min_eigval: Float scalar, <<1. 
        The minimum eigenvalue to use in inverting the JTJ matrix, to 
        avoid degeneracies in the parameter space (i.e. 'rcond' in 
        np.linalg.lstsq). Default is 1e-12. 
    dl: Float scalar.
        The amount to update parameters by when evaluating derivatives. 
        Default is 1e-6. 
    threept: Bool
        Set to True to use a 3-point stencil instead of a 2-point. More 
        accurate but 20% slower. Default is False. 
    be_nice: Bool
        If True, spends extra updates placing the parameters back to
        their original values after evaluating the derivatives. Default
        is False, i.e. plays fast and dangerous. 
    See Also
    --------
    do_levmarq_all_particle_groups: Convenience wrapper that splits all
        the particles in the state into separate groups, then calls 
        do_levmarq_particles on each group. 
    find_particles_in_box: Given a bounding region finds returns an array
        of the indices of the particles in that box. 
    
    Comments
    --------
    """    
    recalc_J = True
    counter = 0
    
    def do_internal_run():
        """
        Uses the local vars s, damp, run_length, dif_tile, J, JTJ
        """
        print 'Running....'
        for rn in xrange(run_length):
            new_grad = np.dot(J, get_slicered_difference(s, dif_tile.slicer, 
                s.image_mask[dif_tile.slicer].astype('bool')))

            dnew = find_LM_updates(JTJ, new_grad, damp=damp)
            old_err = get_err(s)
            update_particles(s, particles, dnew, relative=True, \
                    fix_errors=True)
            new_err = get_err(s)
            print '%f\t%f' % (old_err, new_err)
            if new_err > old_err:
                #done running, put back old params
                update_particles(s, particles, -dnew, relative=True, \
                        fix_errors=True)
                break
    
    while counter < num_iter:
        # p0 = s.state[block].copy() -- actually I don't know if I want to use this
        err_start = get_err(s)
        
        #1. Get J, JJT, 
        if recalc_J:
            dif_tile = get_tile_from_multiple_particle_change(s, particles)
            J = eval_many_particle_grad(s, particles, slicer=dif_tile.slicer, 
                    **kwargs)
            JTJ = j_to_jtj(J)

        #2. Get -grad from the tiles:
        grad = np.dot(J, get_slicered_difference(s, dif_tile.slicer, 
                s.image_mask[dif_tile.slicer].astype('bool')))
        
        #3. get LM updates: -- here down is practically copied; could be moved into an engine
        d0 = find_LM_updates(JTJ, grad, damp=damp)
        d1 = find_LM_updates(JTJ, grad, damp=damp*ddamp)
        
        update_particles(s, particles, d0, relative=True, fix_errors=True)
        err0 = get_err(s)
        d1md0 = d1-d0 #we need update_particles to modify this in place
        # update_particles(s, particles, d1-d0, relative=True, fix_errors=True)
        update_particles(s, particles, d1md0, relative=True, fix_errors=True)
        err1 = get_err(s)
        
        #4. Pick the best value, continue
        if np.min([err0, err1]) > err_start: #Bad step...
            print 'Bad step!\t%f\t%f\t%f' % (err_start, err0, err1)
            # update_particles(s, particles, -d1, relative=True)
            update_particles(s, particles, -d1md0-d0, relative=True)
            if get_err(s) > (err_start + 1e-3):#0.1):
                # raise RuntimeError('Problem with putting back d1')
                warnings.warn('Problem with putting back d1; resetting', RuntimeWarning)
                s.reset()
            recalc_J = False
            #Avoiding infinite loops by adding a small amount to counter:
            counter += 0.1 
            if err0 < err1: 
                #d_damp is the wrong "sign", so we invert:
                print 'Inverting ddamp:\t%f\t%f' % (ddamp, 1.0/ddamp)
                ddamp = 1.0/ddamp
            else: 
                #ddamp is the correct sign but damp is too big:
                damp *= (ddamp*ddamp)
        
        else: #at least 1 good step:
            if err0 < err1: #good step and damp, re-update:
                update_particles(s, particles, d1md0, relative=True)
                print 'Good step:\t%f\t%f\t%f' % (err_start, err0, err1)
            else: #err1 < err0 < err_start, good step but decrease damp:
                damp *= ddamp
                print 'Changing damping:\t%f\t%f\t%f' % (err_start,err0,err1)
            if do_run:
                do_internal_run()
            recalc_J = True
            counter += 1

def separate_particles_into_groups(s, region_size=40, bounds=None, **kwargs):
    """
    Given a state, returns a list of groups of particles. Each group of 
    particles are located near each other in the image. Every particle 
    located in the desired region is contained in exactly 1 group. 
    
    Parameters:
    -----------
    s : State
        The cbamf state to find particles in. 
    region_size: Int or 3-element list-like of ints. 
        The size of the box. Groups particles into boxes of shape
        (region_size[0], region_size[1], region_size[2]). If region_size
        is a scalar, the box is a cube of length region_size. 
        Default is 40.
    bounds: 2-element list-like of 3-element lists. 
        The sub-region of the image over which to look for particles. 
            bounds[0]: The lower-left  corner of the image region. 
            bounds[1]: The upper-right corner of the image region. 
        Default (None -> ([0,0,0], s.image.shape)) is a box of the entire
        image size, i.e. the default places every particle in the image
        somewhere in the groups.
        
    Returns:
    -----------
    particle_groups: List
        Each element of particle_groups is an int numpy.ndarray of the
        group of nearby particles. Only contains groups with a nonzero
        number of particles, so the elements don't necessarily correspond
        to a given image region. 
    """
    if bounds is None:
        bounds = ([0,0,0], s.image.shape)
    if type(region_size) == int:
        rs = [region_size, region_size, region_size]
    else:
        rs = region_size
        
    pts = [range(bounds[0][i], bounds[1][i], rs[i]) for i in xrange(3)]

    all_boxes = []
    for start_0 in pts[0]:
        for start_1 in pts[1]:
            for start_2 in pts[2]:
                all_boxes.append([[start_0, start_1, start_2], 
                        [start_0+rs[0], start_1+rs[1], start_2+rs[2]]])
    
    particle_groups = []
    for box in all_boxes:
        cur_group = find_particles_in_box(s, box)
        if cur_group.size > 0:
            particle_groups.append(cur_group)
        
    return particle_groups 

def do_levmarq_all_particle_groups(s, region_size=40, calc_region_size=False, 
        max_mem=4e9, **kwargs):
    """
    Runs an exact Levenberg-Marquardt minimization on all the particles
    in the state, by splitting them up into groups of nearby particles
    and running do_levmarq_particles on each group. 
    This is a wrapper for do_levmarq_particles, so see its documentation for
    further details. 
    
    Parameters:
    -----------
    s : State
        The cbamf state to optimize. 
    region_size: Int or 3-element numpy.ndarray
        The size of the box for particle grouping, through 
        separate_particles_into_groups. This groups particles into 
        boxes of shape (region_size, region_size, region_size). Default
        is 40. 
    calc_region_size: Bool
        Set to True to calculate an approximate region size based on a 
        maximum allowed memory for J. Very rough / a little bleeding edge.
        Default is False. 
    max_mem: Numeric
        The approximate maximum memory for J. Finds the region size with 
        a very rough estimate, so this can be off by a factor of 10 or more. 
        Default is 4e9. 

    **kwargs parameters of interest:
    ------------
    damp: Float scalar, >=0. 
        The damping parameter in the Levenberg-Marquardt optimization.
        Big damping means gradient descent with a small step, damp=0
        means Hessian inversion. Default is 0.1. 
    ddamp: Float scalar, >0. 
        Multiplicative value to update damp by. Internally decides when
        to update and when to use damp or 1/damp. Default is 0.2. 
    num_iter: Int. 
        Number of Levenberg-Marquardt iterations to execute. Default is 2.
    """
    
    def calc_mem_usage(region_size):
        rs = np.array(region_size)
        particle_groups = separate_particles_into_groups(s, region_size=
                rs.tolist(), **kwargs)
        num_particles = np.max(map(np.size, particle_groups))
        mem_per_part = 32 * np.prod(rs + 2*s.pad*np.ones(3))
        return num_particles * mem_per_part
    
    if calc_region_size:
        if calc_mem_usage(region_size) > max_mem:
            while calc_mem_usage(region_size) and np.any(region_size > 2):
                region_size -= 1
        else:
            while calc_mem_usage(region_size) and np.all(region_size < np.array(s.image.shape)):
                region_size += 1
            region_size -= 1
    
    particle_groups = separate_particles_into_groups(s, region_size=region_size,
            **kwargs)
    for group in particle_groups:
        do_levmarq_particles(s, group, **kwargs)
        #then there is a problem with the psf (i think???) being too big
        #and particle updates not being exact, so....
        s.reset()
        #i.e. FIXME
    