#!/usr/bin/env python -t
# -*- mode: Python; py-indent-offset: 2; -*-

from __future__ import print_function

__author__ = "Jim Randell <jim.randell@gmail.com>"
__version__ = "2019-10-28"

import collections
import re

import subprocess
import tempfile
import os

import sys
if sys.version_info[0] == 2:
  # Python 2.x
  _python = 2
  range = xrange
  basestring = basestring
elif sys.version_info[0] > 2:
  # Python 3.x
  _python = 3
  range = range
  basestring = str

# parse an mzn value to a python value, currently we can handle:
#   "true" | "false" -> True | False
#   int -> int
#   float -> float
#   array -> dict
def parse(s):
  # array:              (dim)   (idx) (vs)
  m = re.search(r'^array(\d+)d\((.+)\[(.+)\]\)', s)
  if m:
    return parse_array(int(m.group(1)), re.split(r'\s*,\s*', m.group(2)), re.split(r'\s*,\s*', m.group(3)))
  for fn in (parse_bool, int, float):
    try:
      return fn(s)
    except ValueError:
      continue
  return None

# parse an mzn array to a python dict()
def parse_array(d, i, vs):
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
      v[j] = parse_array(d - 1, i[1:], vs)
    return v
  return None

# parse a bool
def parse_bool(s):
  if s == "true": return True
  if s == "false": return False
  raise ValueError

_defaults = {
  'model': None,
  'result': None,
  'solver': 'minizinc -a', # formerly: 'mzn-gecode -a'
  'encoding': 'utf-8',
  'use_shebang': 0,
  'verbose': 0,
  # additional arguments require for win32
  'mzn_dir': None,
  'use_shell': False,
}

import sys
if sys.platform == "win32":
  # some possible places that MiniZinc might be installed
  # if none of these work use the 'mzn_dir' parameter
  ps = [
    r'C:/Program Files/MiniZinc IDE (bundled)',
    r'C:/Program Files/MiniZinc IDE',
    r'C:/Program Files/MiniZinc',
    r'C:/Program Files (x86)/MiniZinc IDE (bundled)',
    r'C:/Program Files (x86)/MiniZinc IDE',
    r'C:/Program Files (x86)/MiniZinc',
  ]
  for p in ps:
    if os.path.isdir(p):
      _defaults['mzn_dir'] = p
      break
  _defaults['use_shell'] = True

class MiniZinc(object):
  """
  Parameters can be specified as keyword arguments either during
  construction (in the call to MiniZinc()) or when calling solve()
  on the resulting object.

  Parameters:

    model = the MiniZinc model (default: None)
    result = how to return the results (default: None)
    solver = the solver to use (default: "minizinc -a")
    encoding = encoding used by MiniZinc (default: "utf-8")
    use_shebang = if true, get 'solver' from model (default: 0)
    verbose = output additional information (default: 0)

    mzn_dir = MiniZinc install directory (default: None)
    use_shell = use the shell to execute commands (default: False)

  The "model" parameter can be the text of the MiniZinc model,
  or the path of a file containing the model.

  If the "result" parameter is specified is should be an acceptable
  field_names parameter to collections.namedtuple(), and these fields
  will be returned for each result as a namedtuple().

  If the "result" parameter is None (the default) then the results
  are returned as a collections.OrderedDict().

  If the "use_shebang" parameter is set to true then the first line of
  the model will be interrogated for a specification "%#! <solver>".

  If the MiniZinc executables are not on PATH or in any of the
  expected places you can specify the directory where they are using
  "mzn_dir", and the MiniZinc command will be executed in that directory.
  This may be needed on MS Windows.

  Also on MS Windows "use_shell" defaults to True.
  """ #"

  def __init__(self, model=None, **args):
    self._setattrs(_defaults)
    self._setattrs(args)
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
    
    # can set MZN_DEBUG to override arguments, e.g.:
    #   MZN_DEBUG="solver=mzn-gecode -a; verbose=3"
    mzn_debug = os.getenv("MZN_DEBUG")
    if mzn_debug:
      print(">>> MZN_DEBUG={mzn_debug}".format(mzn_debug=mzn_debug))
      for x in re.split(r';\s*', mzn_debug):
        (k, _, v) = x.partition('=')
        if not(k and v): continue
        if k in ['verbose', 'use_shebang', 'use_shell']: v = int(v)
        args[k] = v

    model = self._getattr('model', args)
    result = self._getattr('result', args)
    solver = self._getattr('solver', args)
    encoding = self._getattr('encoding', args)
    use_shebang = self._getattr('use_shebang', args)
    verbose = self._getattr('verbose', args)
    # additional arguments required on win32
    mzn_dir = self._getattr('mzn_dir', args)
    use_shell = self._getattr('use_shell', args)

    # if mzn_dir is specified, if should be a directory
    if mzn_dir and not(os.path.isdir(mzn_dir)):
      print("WARNING: cannot find MiniZinc directory \"{mzn_dir}\"".format(mzn_dir=mzn_dir))

    # result value
    if result:
      Value = collections.namedtuple('Value', result)

    # if the model is not a string, turn it into one
    if not isinstance(model, basestring):
      model = os.linesep.join(model)

    # is the model already a file? (possible race condition here)
    create = 1
    if os.path.isfile(model):
      (create, path) = (0, model)
    else:
      # try looking in the same directory as the script
      x = sys.argv[0]
      if x:
        x = os.path.join(os.path.dirname(os.path.abspath(x)), model)
        if os.path.isfile(x):
          (create, path) = (0, x)
    if create:
      (fd, path) = tempfile.mkstemp(suffix='.mzn', text=False)

    try:
      if create:
        # write the model in the appropriate encoding
        os.write(fd, model.encode(encoding))
        os.close(fd)

      if use_shebang and 'solver' not in args:
        # possible race condition here
        shebang = "#!"
        with open(path, 'r') as fh:
          s = next(fh)
          i = s.find(shebang)
          assert i != -1, "interpreter not found"
          solver = s[i + len(shebang):].strip()
          #print("use_shebang: solver={solver}".format(solver=solver))

      # solver should be a list
      if type(solver) is not list:
        import shlex
        solver = shlex.split(solver)

      # run minizinc
      if verbose > 2: print(">>> model=\"\"\"\n{model}\n\"\"\"".format(model=model.strip()))
      if verbose > 2: print(">>> path={path}".format(path=path))
      if verbose > 1: print(">>> solver={solver}".format(solver=solver))
      p = subprocess.Popen(solver + [path], stdout=subprocess.PIPE, bufsize=-1, cwd=mzn_dir, shell=use_shell)
      d = None
      while True:
        s = p.stdout.readline()
        if not s: break
        # read output (in the appropriate encoding)
        s = s.decode(encoding).rstrip()
        #print(">>> {s} <<<".format(s=s))
        if re.search(r'^-+$', s):
          #print("<{s}> end of record".format(s=s))
          if verbose > 0: print(">>> solution: " + str.join(' ', (k + "=" + repr(v) for (k, v) in d.items())))
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
      if create:
        # remove the temporary file
        os.unlink(path)

  def go(self, **args):
    """
    solve the MiniZinc model and output solutions.

    fmt - specify output format
    """
    fmt = args.pop('fmt', None)
    for s in self.solve(**args):
      try:
        s = s._asdict()
      except AttributeError:
        pass
      if fmt:
        print(substitute(fmt, s))
      else:
        print(str.join(' ', (k + "=" + repr(v) for (k, v) in s.items())))

  def substitute(self, s, t):
    """
    use solution s to substitute symbols in text t.
    """
    return str.join('', map(str, (s.get(x, x) for x in t)))


# helper functions for interpolation in MiniZinc models

# declare a bunch of minizinc variables
def var(*args):
  if len(args) == 2:
    # var("0..9", "xyz")
    (domain, vars) = args
    pre = ""
  elif len(args) == 3:
    # var("array[0..9] of", "0..9", "ABC")
    (pre, domain, vars) = args
    pre += " "
  else:
    raise ValueError
  return str.join(";\n", ("{pre}var {domain}: {v}".format(pre=pre, domain=domain, v=v) for v in vars))

# replace word with the alphametic equivalent expression
def _word(w, base):
  (m, d) = (1, dict())
  for x in w[::-1]:
    d[x] = d.get(x, 0) + m
    m *= base
  return "(" + str.join(' + ', (str.join('', (str(k),) + (() if v == 1 else ('*', str(v)))) for (k, v) in d.items())) + ")"

# make a function to expand the alphametic words in s
def make_alphametic(symbols, base=10):
  def alphametic(s):
    f = lambda m: _word(m.group(0), base)
    return re.sub('[' + symbols + ']+', f, s)
  return alphametic

# expand alphametic words (enclosed in braces) in s
def alphametic(s, base=10):
  return re.sub('{(\w+?)}', lambda m: _word(m.group(1), base), s)

# substitute ...
def substitute(s, d):
  fn = (d if callable(d) else lambda x: str(d.get(x, '?')))
  return re.sub('{(\w+?)}', lambda m: str.join('', (fn(x) for x in m.group(1))), s)
