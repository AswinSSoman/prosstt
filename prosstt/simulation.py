#!/usr/bin/env python
# coding: utf-8
"""
This module contains all the functions that produce simulations. This includes
the simulation of expression programs, coefficients that map expr. programs to
genes, and different sampling strategies for (pseudotime, branch) pairs.
"""

import sys
import warnings

import numpy as np
from numpy import random
import pandas as pd
import scipy as sp

from prosstt import sim_utils as sut
from prosstt import count_model as cm


def simulate_expression_programs(tree, tol):
    """
    Simulate the relative expression of the lineage tree expression programs
    for each branch.

    Parameters
    ----------
    tol: float
        Correlation cut-off between expression programs
    
    Returns
    -------
    programs: dict
        Relative expression for all expression programs on every branch of the
        lineage tree
    """
    if tol > 1 or tol < 0:
        raise ValueError("value of 'tol' parameter should be between 0 and 1")
    programs = {}
    for branch in tree.branches:
        programs[branch] = sim_expr_branch(tree.time[branch], tree.modules,
                                           cutoff=tol)
    return programs


def sim_expr_branch(T, K, cutoff=0.5, max_loops=100):
    """
    Return K diffusion processes of length T as a matrix W. The output of
    sim_expr_branch is complementary to _sim_coeff_beta.

    W encodes how a group of K coexpressed genes will behave through
    differentiation time. This matrix describes one branch of a
    differentiation tree (between two branch points or between a branch point
    and an endpoint). W describes the module in terms of relative expression
    (from 0 to a small positive float, so from a gene not being expressed to a
    gene being expressed at 2x, 3x of its "normal" level).

    After each new diffusion process is added the function checks whether the
    new diffusion correlates with any of the older ones. If the correlation is
    too high (above 0.5 per default), the last diffusion process will be
    replaced with a new one until one is found that does not correlate with any
    other columns of W or a suitable replacement hasn't been found after 100
    tries.

    Obviously this gets more probable the higher the number of components is -
    it might be advisable to change the number of maximum loops allowed or
    the cutoff in order to reduce runtime for a high number of components.

    Parameters
    ----------
    T: int
        The length of the branch of the differentiation tree
    K: int
        The number of components/modules of coexpression that describe the
        differentiation in this branch of the tree
    cutoff: float, optional
        Correlation above the cut-off will be considered too much. Should be
        between 0 and 1 but is not explicitly tested
    max_loops: int, optional
        The maximum number of times the method will try simulating a new
        diffusion process that doesn't correlate with all previous ones in W
        before resetting the matrix and starting over
    
    Returns
    -------
    W: ndarray
        Output array
    """
    W = np.zeros((K, T))
    k = 0
    loops = 0
    while k < K:
        W[k] = diffusion(T)

        correlates = sut.test_correlation(W, k, cutoff)
        if correlates:
            # repeat and hope it works better this time
            loops += 1
            continue
        else:
            loops = 0
            k += 1

        if loops > max_loops:
            # we tried so hard
            # and came so far
            # but in the end
            # it doesn't even matter
            return sim_expr_branch(T, K, cutoff=cutoff)

    return np.transpose(W)


def diffusion(steps):
    """
    Diffusion process with momentum term. Returns a random walk with values
    usually between 0 and 1.

    Parameters
    ----------
    steps: int
        The length of the diffusion process.

    Returns
    -------
    W: float array
        A diffusion process with a specified number of steps.
    """
    V = np.zeros(steps)
    W = np.zeros(steps)

    W[0] = sp.stats.uniform.rvs()
    V[0] = sp.stats.norm.rvs(loc=0, scale=0.2)

    s_eps = 1 / steps
    eta = sp.stats.uniform.rvs()

    for t in range(0, steps - 1):
        W[t + 1] = W[t] + V[t]

        epsilon = sp.stats.norm.rvs(loc=0, scale=s_eps)
        # amortize the update
        V[t + 1] = 0.95 * V[t] + epsilon - eta * V[t]

        # quality control: we are not (?) allowed to go below 0. If it happens,
        # reverse and dampen velocity
        # if W[t+1] <= 0:
        #     W[t+1] = W[t]
        #     V[t+1] = -0.2 * V[t]
    return W


def simulate_coefficients(tree, a=0.05, **kwargs):
    """
    H encodes how G genes are expressed by defining their membership to K
    expression modules (coded in a matrix W). H could be told to encode
    metagenes, as it contains the information about which genes are coexpressed
    (genes that belong to/are influenced by the same modules). The influence of
    a module on a gene is measured by a number between 0 and 1, drawn from a
    (symmetric, if used with default values) beta distribution.

    The result of simulate_H is complementary to sim_expr_branch.

    Parameters
    ----------
    tree: Tree

    a: float, optional
        Shape parameter of Gamma distribution or first shape parameter of Beta
        distribution
    **kwargs: float
        Additional parameter (float b) if Beta distribution is to be used
    
    Returns
    -------
    A sparse matrix of the contribution of K expression programs to G genes.
    """
    if "a" not in kwargs.keys():
        warnings.warn(
            "No argument 'a' specified in kwargs: using gamma and a=0.05", UserWarning)
        return _sim_coeff_gamma(tree, a)
    # if a, b are present: beta distribution
    if "b" in kwargs.keys():
        groups = sut.create_groups(tree.modules, tree.G)
        return _sim_coeff_beta(tree, groups)
    else:
        return _sim_coeff_gamma(tree, a=kwargs['a'])


def _sim_coeff_beta(tree, groups, a=2, b=2):
    """
    Draw weights for the contribution of tree expression programs to gene
    expression from a Beta distribution.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    groups: list of ints
        A list of the two modules to which each gene belongs
    a: float, optional
        First shape parameter of the Beta distribution
    b: float, optional
        Second shape parameter of the Beta distribution
    
    Returns
    -------
    H: ndarray
        Output array
    """
    H = np.zeros((tree.modules, tree.G))
    for k in range(tree.modules):
        for gene in groups[k]:
            H[k][gene] += sp.stats.beta.rvs(a, b)
    return H


def _sim_coeff_gamma(tree, a=0.05):
    """
    Draw weights for the contribution of tree expression programs to gene
    expression from a Gamma distribution.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    a: float, optional
        Shape parameter of the Gamma distribution
    
    Returns
    -------
    H: ndarray
        Output array
    """
    K = tree.modules
    G = tree.G
    coefficients = np.reshape(sp.stats.gamma.rvs(a, size=K * G), (K, G))
    return coefficients


def simulate_lineage(tree, intra_branch_tol=0.4, inter_branch_tol=0.5, **kwargs):
    """
    Simulate gene expression for each point of the lineage tree (each
    possible pseudotime/branch combination). The simulation will try to make
    sure that a) gene expression programs within the same branch don't correlate
    too heavily and b) gene expression programs in parallel branches diverge
    enough.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    intra_branch_tol: float, optional
        The threshold for correlation between expression programs in the same
        branch
    inter_branch_tol: float, optional
        The threshold for anticorrelation between relative gene expression in
        parallel branches
    **kwargs: various, optional
        Accepts parameters for coefficient simulation; float a if coefficients
        are generated by a Gamma distribution or floats a, b if the coefficients
        are generated by a Beta distribution
    
    Returns
    -------
    relative_means: Series
        Relative mean expression for all genes on every lineage tree branch
    programs: Series
        Relative expression for all expression programs on every branch of the
        lineage tree
    coefficients: ndarray
        Array that contains the contribution weight of each expr. program for
        each gene
    """
    if not len(tree.time) == tree.num_branches:
        print("the parameters are not enough for %i branches" %
              tree.num_branches)
        sys.exit(1)

    coefficients = simulate_coefficients(tree, **kwargs)
    programs = simulate_expression_programs(tree, intra_branch_tol)

    # check that parallel branches don't overlap too much
    programs, relative_means = correct_parallel(tree, programs, coefficients, intra_branch_tol, inter_branch_tol)

    # adjust the ends of the relative mean expression matrices
    for b in tree.topology:
        relative_means[b[1]] = sut.bifurc_adjust(relative_means[b[1]], relative_means[b[0]])

    return (pd.Series(relative_means),
            pd.Series(programs),
            coefficients)


def correct_parallel(tree, programs, coefficients, intra_branch_tol=0.2, inter_branch_tol=0.5):
    """
    Check if parallel branches diverge and if not re-draw the expression
    programs for these branches.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    programs: dict
        Relative expression for all expression programs on every branch of the
        lineage tree
    coefficients: ndarray
        A sparse matrix of the contribution of K expression programs to G genes
    intra_branch_tol: float, optional
        The threshold for correlation between expression programs in the same
        branch
    inter_branch_tol: float, optional
        The threshold for anticorrelation between relative gene expression in
        parallel branches

    Returns
    -------
    programs: dict
        Relative expression for all expression programs on every branch of the
        lineage tree
    relative_means: dict
        Relative gene expression for each tree branch
    """
    # calculate relative means over tree
    relative_means = sut.calc_relat_means(tree, programs, coefficients)
    # find parallel branches
    parallel = tree.get_parallel_branches()
    # for all parallel branches check if they are diverging.
    # if not, fix.
    for key in parallel:
        diverges = sut.diverging_parallel(parallel[key], relative_means,
                                          tree.G, tol=inter_branch_tol)
        while not all(diverges):
            for branch in parallel[key]:
                programs[branch] = sim_expr_branch(tree.time[branch],
                                                   tree.modules,
                                                   cutoff=intra_branch_tol)
                relative_means[branch] = np.dot(programs[branch], coefficients)
            diverges = sut.diverging_parallel(parallel[key], relative_means,
                                              tree.G, tol=inter_branch_tol)
    return programs, relative_means


def sample_whole_tree_restricted(tree, alpha=0.2, beta=3, gene_loc=0.8, gene_s=1):
    """
    Bare-bones simulation where the lineage tree is simulated using default
    parameters. Branches are assigned randomly if multiple are possible.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    alpha: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    beta: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    gene_loc: float, optional
        Mean of the log-normal distribution of base gene expression values
    gene_s: float, optional
        Standard deviation of base gene expression value distribution
        (log-normal)
    
    Returns
    -------
    expr_matrix: ndarray
        Expression matrix of the differentiation
    sample_pt: ndarray
        Pseudotime values of the sampled cells
    branches: ndarray
        The branch to which each simulated cell belongs
    scalings: ndarray
        Library size scaling factor for each cell
    """
    sample_time = np.arange(0, tree.get_max_time())
    gene_scale = np.exp(sp.stats.norm.rvs(
        loc=gene_loc, scale=gene_s, size=tree.G))
    Ms = {}
    while not sut.are_lengths_ok(Ms):
        uMs, Ws, Hs = simulate_lineage(tree, a=0.05)
        for i in tree.branches:
            Ms[i] = np.exp(uMs[i]) * gene_scale

    tree.add_genes(Ms)
    alphas, betas = cm.generate_negbin_params(tree, alpha=alpha, beta=beta)

    return _sample_data_at_times(tree, sample_time, alphas, betas)


def sample_pseudotime_series(tree, cells, series_points, point_std, alpha=0.3, beta=2, scale=True, scale_v=0.7, verbose=True):
    """
    Simulate the expression matrix of a differentiation if the data came from
    a time series experiment.

    Taking a sample from a culture of differentiating cells returns a mixture of
    cells at different stages of progress through differentiation (pseudotime).
    A time series experiment consists of sampling at multiple time points. This
    is simulated by drawing normally distributed pseudotime values around
    pseudotime sample points.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    cells: list or int
        If a list, then the number of cells to be sampled from each sample
        point. If an integer, then the total number of cells to be sampled
        (will be divided equally among all sample points)
    series_points: list
        A list of the pseudotime sample points
    point_std: list or float
        The standard deviation with which to sample around every sample point.
        Use a list for differing std at each time point.
    alpha: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    beta: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    scale: True, optional
        Apply cell-specific library size factor to average gene expression
    scale_v: float, optional
        Variance for the drawing of scaling factors (library size) for each cell
    verbose: bool, optional
        Print a progress bar or not

    Returns
    -------
    expr_matrix: ndarray
        Expression matrix of the differentiation
    sample_pt: ndarray
        Pseudotime values of the sampled cells
    branches: ndarray
        The branch to which each simulated cell belongs
    scalings: ndarray
        Library size scaling factor for each cell
    """
    series_points, cells, point_std = sut.process_timeseries_input(series_points, cells, point_std)
    pseudotimes = []

    max_time = tree.get_max_time()
    for t, n, var in zip(series_points, cells, point_std):
        times_around_t = draw_times(t, n, max_time, var)
        pseudotimes.extend(times_around_t)
    return _sample_data_at_times(tree, pseudotimes, alpha=alpha, beta=beta,
                                 scale=scale, scale_v=scale_v, verbose=verbose)


def draw_times(timepoint, no_cells, max_time, var=4):
    """
    Draw cell pseudotimes around a certain sample time point under the
    assumption that in an asynchronously differentiating population cells are
    normally distributed around t. The variance of the normal distribution
    controls the speed of differentiation (high spread: transient state/fast
    differentiation, low spread: bottleneck/slow differentiation).

    Parameters
    ----------
    timepoint: int
        The pseudotime point that represents the current mean differentiation
        stage of the population.
    no_cells: int
        How many cells to sample.
    max_time: int
        All time points that exceed the differentiation duration will be
        mapped to the end of the differentiation.
    var: float, optional
        Variance of the normal distribution we use to draw pseudotime points.
        In the experiment metaphor this parameter controls synchronicity.

    Returns
    -------
    sample_pt: int array
        Pseudotime points around <timepoint>.
    """
    sample_pt = sp.stats.norm.rvs(loc=timepoint, scale=var, size=no_cells)
    sample_pt = sample_pt.astype(int)
    sample_pt[sample_pt < 0] = 0
    sample_pt[sample_pt >= max_time] = max_time - 1
    return sample_pt


def sample_density(tree, N, alpha=0.3, beta=2, scale=True, scale_v=0.7, verbose=True):
    """
    Use cell density along the lineage tree to sample pseudotime/branch pairs
    for the expression matrix.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    N: int
        Number of cells to sample
    alpha: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    beta: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    scale: True, optional
        Apply cell-specific library size factor to average gene expression
    scale_v: float, optional
        Variance for the drawing of scaling factors (library size) for each cell
    verbose: bool, optional
        Print a progress bar or not
    
    Returns
    -------
    expr_matrix: ndarray
        Expression matrix of the differentiation
    sample_pt: ndarray
        Pseudotime values of the sampled cells
    branches: ndarray
        The branch to which each simulated cell belongs
    scalings: ndarray
        Library size scaling factor for each cell
    """
    bt = tree.branch_times()

    possible_pt = [np.arange(bt[b][0], bt[b][1] + 1) for b in tree.branches]
    possible_branches = [[b] * tree.time[b] for b in tree.branches]
    probabilities = [tree.density[b] for b in tree.branches]

    # make numpy arrays and flatten lists
    probabilities = np.array(probabilities).flatten()
    possible_pt = np.array(possible_pt).flatten()
    possible_branches = np.array(possible_branches).flatten()

    # select according to density and take the selected elements
    sample = random.choice(np.arange(len(probabilities)), size=N, p=probabilities)
    sample_time = possible_pt[sample]
    sample_branches = possible_branches[sample]

    return _sample_data_at_times(tree, sample_time, alpha=alpha, beta=beta,
                                branches=sample_branches, scale=scale,
                                scale_v=scale_v, verbose=verbose)


def sample_whole_tree(tree, n_factor, alpha=0.3, beta=2, scale=True, scale_v=0.7, verbose=True):
    """
    Every possible pseudotime/branch pair on the lineage tree is sampled a
    number of times.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    n_factor: int
        How many times each pseudotime/branch combination can be present
    alpha: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    beta: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    scale: True, optional
        Apply cell-specific library size factor to average gene expression
    scale_v: float, optional
        Variance for the drawing of scaling factors (library size) for each cell
    verbose: bool, optional
        Print a progress bar or not
    
    Returns
    -------
    expr_matrix: ndarray
        Expression matrix of the differentiation
    sample_pt: ndarray
        Pseudotime values of the sampled cells
    branches: ndarray
        The branch to which each simulated cell belongs
    scalings: ndarray
        Library size scaling factor for each cell
    """
    pseudotime, branches = cover_whole_tree(tree)

    branches = np.repeat(branches, n_factor)
    pseudotime = np.repeat(pseudotime, n_factor)

    return _sample_data_at_times(tree, pseudotime, alpha=alpha, beta=beta,
                                 branches=branches, scale=scale,
                                 scale_v=scale_v, verbose=verbose)


def cover_whole_tree(tree):
    """
    Get all the pseudotime/branch pairs that are possible in the lineage tree.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    
    Returns
    -------
    pseudotime: ndarray
        Pseudotime values of all positions in the lineage tree
    branches: ndarray
        Branch assignments of all positions in the lineage tree
    """
    timezone = tree.populate_timezone()
    assignments = sut.assign_branches(tree.branch_times(), timezone)
    pseudotime = list()
    branches = list()

    for n, a in enumerate(timezone):
        start = a[0]
        end = a[1] + 1
        length = end - start
        for b in assignments[n]:  # for all possible branches in timezone a
            pseudotime.extend(np.arange(start, end))
            branches.extend([b] * length)
    return pseudotime, branches


def _sample_data_at_times(tree, sample_pt, branches=None, alpha=0.3, beta=2, scale=True, scale_v=0.7, verbose=True):
    """
    Sample cells from the lineage tree for given pseudotimes. If branch
    assignments are not specified, cells will be randomly assigned to one of the
    possible branches.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    sample_pt: ndarray
        Pseudotime values for the cells to be sampled
    branches: ndarray, optional
        Branch assignment of the cells to be sampled
    alpha: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    beta: float or ndarray, optional
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    scale: True, optional
        Apply cell-specific library size factor to average gene expression
    scale_v: float, optional
        Variance for the drawing of scaling factors (library size) for each cell
    verbose: bool, optional
        Print a progress bar or not
    
    Returns
    -------
    expr_matrix: ndarray
        Expression matrix of the differentiation
    sample_pt: ndarray
        Pseudotime values of the sampled cells
    branches: ndarray
        The branch to which each simulated cell belongs
    scalings: ndarray
        Library size scaling factor for each cell
    """
    N = len(sample_pt)
    if np.shape(alpha) == ():
        alpha = [alpha] * tree.G
    if np.shape(beta) == ():
        beta = [beta] * tree.G
    if branches is None:
        branches = sut.pick_branches(tree, sample_pt)
    scalings = sut.calc_scalings(N, scale, scale_v)
    expr_matrix = draw_counts(tree, sample_pt, branches, scalings, alpha, beta, verbose)
    return expr_matrix, sample_pt, branches, scalings


def draw_counts(tree, pseudotime, branches, scalings, alpha, beta, verbose):
    """
    For all the cells in the lineage tree described by a given pseudotime and
    branch assignment, sample UMI count values for all genes. Each cell is an
    expression vector; the combination of all cell vectors builds the expression
    matrix.

    Parameters
    ----------
    tree: Tree
        A lineage tree
    pseudotime: ndarray
        Pseudotime values for all cells to be sampled
    branches: ndarray
        Branch assignments for all cells to be sampled
    scalings: ndarray
        Library size scaling factor for all cells to be sampled
    alpha: float or ndarray
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    beta: float or ndarray
        Parameter for the count-drawing distribution. Float if it is the same
        for all genes, else an ndarray
    verbose: bool
        Print a progress bar or not
    
    Returns
    -------
    expr_matrix: ndarray
        Expression matrix of the differentiation
    """
    N = len(branches)
    expr_matrix = np.zeros((N, tree.G))
    custm = cm.my_negbin()

    for n, t, b in zip(np.arange(N), pseudotime, branches):
        T_off = tree.branch_times()[b][0]
        M = tree.means[b]

        for g in range(tree.G):
            try:
                mu = M[t - T_off][g] * scalings[n]
            except IndexError:
                print("IndexError for g=%d, t=%d, T_off=%d in branch %s" %
                      (g, t, T_off, b))
                mu = M[-1][g] * scalings[n]
            p, r = cm.get_pr_umi(a=alpha[g], b=beta[g], m=mu)
            expr_matrix[n][g] = custm.rvs(p, r)

        if verbose:
            sut.print_progress(n, len(branches))
    return expr_matrix
