#!/usr/bin/env python -t
# -*- mode: Python; py-indent-offset: 2; -*-

from __future__ import print_function

import collections
import re

import subprocess
import tempfile
import os

# parse an mzn value to a python value
# int -> int
# float -> float
# array -> dict
def parse(s):
  # array:              (dim)   (idx) (vs)
  m = re.search(r'^array(\d+)d\((.+)\[(.+)\]\)', s)
  if m:
    return array(int(m.group(1)), re.split(r'\s*,\s*', m.group(2)), re.split(r'\s*,\s*', m.group(3)))
  for fn in (int, float):
    try:
      return fn(s)
    except ValueError:
      continue
  return None

# parse an mzn array
def array(d, i, vs):
  #print([d, i, vs])
  (s, f) = map(int, re.split(r'\s*\.\.\s*', i[0]))
  if d == 1:
    v = dict()
    for j in range(s, f + 1):
      v[j] = parse(vs.pop(0))
    return v
  else:
    v = dict()
    for j in range(s, f + 1):
      v[j] = array(d - 1, i[1:], vs)
    return v
  return None

_defaults = {
  'model': None,
  'result': None,
  'solver': 'mzn-gecode -a',
  'encoding': 'utf-8',
  'verbose': 0,
}

class MiniZinc(object):
  """
  Parameters can be specified as keyword arguments either during
  construction (in the call to MiniZinc()) or when calling solve()
  on the resulting object.

  Parameters:

    model = the text of the MiniZinc model (default: None)
    result = how to return the results (default: None)
    solver = the solver to use (default: "mzn-gecode -a")
    encoding = encoding used by MiniZinc (default: "utf-8")
    verbose = output additional information (default: 0)

  If the "result" parameter is specified is should be an acceptable
  field_names parameter to collections.namedtuple(), and these fields
  will be returned for each result as a namedtuple().

  If the "result" parameter is None (the default) then the results
  are returned as a collections.OrderedDict().

  """

  def __init__(self, model=None, **args):
    self._setattrs(_defaults)
    self.model = model

  def _setattrs(self, d):
    for (k, v) in d.items():
      setattr(self, k, v)

  def _getattr(self, k, d=None):
    if d and k in d:
      return d[k]
    return getattr(self, k)

  def solve(self, **args):
    """
    solve the MiniZinc model and return solutions as Python objects.
    """
    model = self._getattr('model', args)
    result = self._getattr('result', args)
    solver = self._getattr('solver', args)
    encoding = self._getattr('encoding', args)
    verbose = self._getattr('verbose', args)

    # solver should be a list
    if type(solver) is not list:
      solver = solver.split()

    # result value
    if result:
      Value = collections.namedtuple('Value', result)

    # write the model to a file
    (fd, path) = tempfile.mkstemp(suffix='.mzn', text=False)
    try:
      # write the model in the appropriate encoding
      os.write(fd, model.encode(encoding))
      os.close(fd)

      # and run minizinc
      if verbose > 1: print(">>> solver=\"{solver}\"".format(solver=' '.join(solver)))
      p = subprocess.Popen(solver + [path], stdout=subprocess.PIPE, bufsize=1)
      d = None
      while True:
        s = p.stdout.readline()
        if not s: break
        # read output (in the appropriate encoding)
        s = s.decode(encoding).rstrip()
        if re.search(r'^-+$', s):
          #print("<{s}> end of record".format(s=s))
          if verbose > 0: print(">>> solution: " + ' '.join(k + "=" + repr(v) for (k, v) in d.items()))
          if result:
            yield Value(*(d[k] for k in Value._fields))
          else:
            yield d
          d = None
        else:
          #print(">>> {s} <<<".format(s=s))
          m = re.search(r'^(\w+)\s*=\s*(.+)\s*;$', s)
          #print(">>> {m} <<<".format(m=m))
          if m:
            (k, v) = (m.group(1), m.group(2))
            #print("<{s}> {k} = {v}".format(s=s, k=k, v=v))
            if d is None: d = collections.OrderedDict()
            d[k] = parse(v)

    finally:
      # remove the temporary file
      os.unlink(path)

  def go(self, **args):
    """
    solve the MiniZinc model and output solutions.
    """
    for s in self.solve(**args):
      try:
        s = s._asdict()
      except AttributeError:
        pass
      print(' '.join(k + "=" + repr(v) for (k, v) in s.items()))
