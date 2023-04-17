#! python3
# -*- mode: Python; python-indent-offset: 2; -*-

from __future__ import print_function

# implementation of useful algorithms in MiniZinc (using minizinc.py)

from minizinc import MiniZinc

# find hitting sets
# size = None -> find a minimal cardinality hitting set
# size = int  -> find all hitting sets of specified size
# hit = "> 0", "== 1" -> size of intersection with each set
def hitting_sets(ss, size=None, hit="> 0", solver=None, verbose=0):
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

# find a single hitting set
def hitting_set(ss, size=None, hit="> 0", solver=None, verbose=0):
  for hs in hitting_sets(ss, size=size, hit=hit, solver=solver, verbose=verbose):
    return hs
