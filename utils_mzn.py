#! python3
###############################################################################
#
# File:         utils_mzn.py
# RCS:          $Header: $
# Description:  Useful algorithms in MiniZinc
# Author:       Jim Randell
# Created:      Tue Apr  4 15:47:53 2023
# Modified:     Mon Apr 17 10:59:25 2023 (Jim Randell) jim.randell@gmail.com
# Language:     Python
# Package:      N/A
# Status:       Experimental (Do Not Distribute)
#
# (C) Copyright 2023, Jim Randell, all rights reserved.
#
###############################################################################
# -*- mode: Python; python-indent-offset: 2; -*-

from __future__ import print_function

# implementation of useful algorithms in MiniZinc (using minizinc.py)
#  - hitting_set() / hitting_sets() = minimum cardinality hitting set

from minizinc import MiniZinc

def hitting_sets(ss, size=None, hit="> 0", solver=None, verbose=0):
  """
  find hitting sets for the sets in <ss>.

    size = None -> find a minimal cardinality hitting set.
    size = int  -> find all hitting sets of specified size (solver permitting)

    hit = "> 0", "== 1", ... -> size of intersection with each set

  the following arguments are passed to MiniZinc:

    solver -> command to invoke minizinc (use -a for multiple solutions)
    verbose -> verbosity level
  """
  # find elements in the universe
  vs = sorted(set().union(*ss))
  if not vs:
    yield set()
    return

  # map elements to indices (1-indexed)
  m = dict((v, j) for (j, v) in enumerate(vs, start=1))
  # map the sets to sets of indices
  jss = set(frozenset(m[v] for v in s) for s in ss)
  # can't hit the empty set
  if not all(jss): return

  # construct the model
  model = list()
  # decision variables: x[j] = 1 if element j is in the hitting set
  model.extend([
    str.format("array [1..{n}] of var 0..1: x;", n=len(vs)),
  ])
  # each set must be hit
  for js in jss:
    hsum = str.join(" + ", (str.format("x[{j}]", j=j) for j in js))
    model.extend([
      str.format("constraint {hsum} {hit};", hsum=hsum, hit=hit),
    ])
  if size is None:
    # minimise the size of the hitting set
    model.extend([
      "solve minimize(sum(x));",
    ])
    if solver is None: solver = "minizinc" # don't use -a with minimize()
  else:
    # find all hitting sets of the specified size (depends on the solver)
    model.extend([
      str.format("constraint sum(x) = {size};", size=size),
      "solve satisfy;",
    ])
    if solver is None: solver = "minizinc -a" # use -a to get multiple solutions

  # execute the model (with additional arguments)
  for s in MiniZinc(model, solver=solver, verbose=verbose).solve():
    hs = s['x']
    # return the elements of the hitting set
    yield set(vs[j] for (j, x) in enumerate(hs) if x)

def hitting_set(ss, size=None, hit="> 0", solver=None, verbose=0):
  """
  find a single hitting set.

  see hitting_sets() for arguments.
  """
  for hs in hitting_sets(ss, size=size, hit=hit, solver=solver, verbose=verbose):
    return hs
