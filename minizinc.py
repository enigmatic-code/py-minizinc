#! python3
# -*- mode: Python; py-indent-offset: 2; -*-

from __future__ import print_function

__author__ = "Jim Randell <jim.randell@gmail.com>"
__version__ = "2022-08-31"

import collections
import re
import json

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

# if [[ --output-mode json ]] is passed to minizinc, then the output
# will be parsed by json.loads().
#
# Note: array indices are not returned in JSON output, so results are
# returned as 0-indexed lists.
#
# TODO: newer versions of minizinc have [[ --json-stream ]]

# parse mzn output to Python values, currently we handle:
#   "true" | "false" -> True | False
#   int -> int
#   float -> float
#   array (with indices) -> dict
#   array (without indices) -> list
def parse(s, ctx=None):
  # indexed array - returned as dict() maping index -> value
  # array               (dim)   (idx) (vs)
  m = re.search(r'^array(\d+)d\((.+)\[(.+)\]\)', s)
  if m:
    return parse_array(int(m.group(1)), re.split(r'\s*,\s*', m.group(2)), re.split(r'\s*,\s*', m.group(3)), ctx)
  # unindexed arrays - return as list()
  # 2d array as: "x = [| a, b, c, ... | a, b, c, ... | ... |]"
  # 1d array as: "x = [a, b, c, ...]"
  m = re.search(r'^\[\s*(.+)\s*\]', s)
  if m:
    return parse_array_to_list(m.group(1))
  # literal -> bool, int, float
  for fn in (parse_bool, int, float):
    try:
      return fn(s)
    except ValueError:
      continue
  # verbatim value (could be an enum)
  return s

# parse an mzn array to a Python dict()
def parse_array(d, i, vs, ctx=None):
  #print([d, i, vs])
  # look for index = <number>..<number>
  m = re.match(r'(\d+)\.\.(\d+)$', i[0])
  if m:
    (a, b) = map(int, m.groups())
    js = range(a, b + 1)
  elif ctx:
    # look in the context
    js = ctx._index.get(i[0], None)
  if not js:
    raise ValueError("bad index: " + i[0])
  if d == 1:
    v = dict()
    for j in js:
      v[j] = parse(vs.pop(0), ctx)
    return v
  else:
    v = dict()
    for j in js:
      v[j] = parse_array(d - 1, i[1:], vs, ctx)
    return v
  return None

# parse an mzn array to a Python list
def parse_array_to_list(s):
  m = re.match(r'^\|\s*(.+)\s*\|$', s)
  if m:
    return list(parse_array_to_list(x) for x in re.split(r'\s*\|\s*', m.group(1)))
  return list(parse(x) for x in re.split(r'\s*,\s*', s))

# parse a bool
def parse_bool(s):
  if s == "true": return True
  if s == "false": return False
  raise ValueError("bad bool: " + s)

# find enum definitions
def find_enum_defs(s):
  # beware capturing commented out code with this
  for m in re.finditer(r'\benum\s+(\w+)\s*=\s*\{\s*(.+?)\s*\}', s):
    yield (m.group(1), re.split(r'\s*,\s*', m.group(2)))

_defaults = {
  'model': None,
  'result': None,
  'solver': 'minizinc -a',  # formerly: 'mzn-gecode -a'
  'encoding': 'utf-8',
  'fmt': None,  # output template
  'use_shebang': 0,
  'use_embed': 0,
  'use_enum': 0,
  'verbose': 0,
  # additional arguments require for win32
  'mzn_dir': None,
  'use_shell': False,
}

def usage(xit=1):
  d = _defaults
  print("usage: python minizinc.py <args> <model>")
  print("")
  print("  args:")
  print("    result=<str> [default: <all variables>]")
  print("    solver=<str> [default: {x}]".format(x=d['solver']))
  print("    encoding=<str> [default: {x}]".format(x=d['encoding']))
  print("    use_shebang=<int> [default: {x}]".format(x=d['use_shebang']))
  print("    use_embed=<int> [default: {x}]".format(x=d['use_embed']))
  print("    use_enum=<int> [default: {x}]".format(x=d['use_enum']))
  print("    verbose=<int> [default: {x}]".format(x=d['verbose']))
  print("    mzn_dir=<str> [default: <search>]")
  print("    use_shell=<int> [default: {x}]".format(x=d['use_shell']))
  print("")
  if xit: exit()

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

# read "arg=value" arguments from args
def read_args(args):
  for x in args:
    (k, _, v) = x.partition('=')
    if not(k and v): continue
    if k == 'verbose' or k.startswith('use_'): v = int(v)
    yield (k, v)

# does <path> represent a file?
def is_file(path):
  # does it directly name a file?
  if os.path.isfile(path): return os.path.abspath(path)
  # try looking in the same directory as the script
  x = sys.argv[0]
  if x:
    x = os.path.join(os.path.dirname(os.path.abspath(x)), path)
    if os.path.isfile(x): return x

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
    fmt = output format (default: None)
    use_embed = if true, evaluate embedded Python 3 code in model (default: 0)
    use_shebang = if true, get 'solver' from model (default: 0)
    use_enum = if true, attempt to use enum definitions from model (default: 0)
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
    if d and k in d: return d[k]
    return getattr(self, k)

  # solve the model
  def solve(self, **args):
    """
    solve the MiniZinc model and return solutions as Python objects.
    """

    # can set MZN_DEBUG to override arguments, e.g.:
    #   MZN_DEBUG="solver=mzn-gecode -a; verbose=3"
    mzn_debug = os.getenv("MZN_DEBUG")
    if mzn_debug:
      print(">>> MZN_DEBUG=\"{mzn_debug}\"".format(mzn_debug=mzn_debug))
      for (k, v) in read_args(re.split(r';\s*', mzn_debug)):
        args[k] = v

    model = self._getattr('model', args)
    result = self._getattr('result', args)
    solver = self._getattr('solver', args)
    encoding = self._getattr('encoding', args)
    fmt = self._getattr('fmt', args)
    use_shebang = self._getattr('use_shebang', args)
    use_embed = self._getattr('use_embed', args)
    use_enum = self._getattr('use_enum', args)
    verbose = self._getattr('verbose', args)
    # additional arguments required on win32
    mzn_dir = self._getattr('mzn_dir', args)
    use_shell = self._getattr('use_shell', args)

    if verbose > 2:
      # system info
      print(">>> [system]")
      print(">>>   [python version] {x}".format(x=sys.version_info))
      print(">>>   [sys.platform] {x}".format(x=sys.platform))
      print(">>>   [sys.argv] {x}".format(x=sys.argv))
      # local vars
      print(">>> [vars]")
      print(">>>   [type(model)] {x}".format(x=type(model)))
      (ls, vs) = (locals(), [
        'result', 'solver', 'encoding', 'fmt', 'use_shebang', 'use_embed', 'use_enum',
        'verbose', 'mzn_dir', 'use_shell',
      ])
      for v in vs:
        print(">>>   [{v}] {x}".format(v=v, x=ls[v]))

    # use self as a parsing context
    self._index = args.get('_index', dict())

    # if mzn_dir is specified, if should be a directory
    if mzn_dir and not(os.path.isdir(mzn_dir)):
      print("WARNING: cannot find MiniZinc directory \"{mzn_dir}\"".format(mzn_dir=mzn_dir))

    # result value
    if result:
      Value = collections.namedtuple('Value', result)

    # if the model is not a string, turn it into one
    if not isinstance(model, basestring):
      model = os.linesep.join(model)

    # if the model has embedded Python we need to read it and evaluate the code
    path = is_file(model)
    if use_embed:
      if path:
        with open(path, 'r') as fh:
          model = fh.read()
      # strip comments from the model (from '%' to end of line)
      model = re.sub(r'%(.*)', r'', model)
      # evaluate any embedded python
      if _python > 2:
        model = eval('f' + repr(model))
      else:
        # not supported in Python 2
        print(">>> WARNING: embedded Python code not supported in Python 2")
      # the model is definitely a string
      path = None

    # is the model already a file? (possible race condition here)
    create = 0
    if not path:
      create = 1
      (fd, path) = tempfile.mkstemp(suffix='.mzn', text=False)

    try:
      if create:
        # write the model in the appropriate encoding
        os.write(fd, model.encode(encoding))
        os.close(fd)

      # do we need to read the solver or enum definitions from the model?
      if (use_shebang and 'solver' not in args) or use_enum:

        # possible race condition here
        with open(path, 'r') as fh:

          if use_shebang and 'solver' not in args:
            shebang = "#!"
            s = next(fh)
            i = s.find(shebang)
            assert i != -1, "interpreter not found"
            solver = s[i + len(shebang):].strip()
            #print("use_shebang: solver={solver}".format(solver=solver))

          if use_enum:
            if create:
              text = model
            else:
              fh.seek(0)
              text = fh.read()

            # strip out comments
            text = re.sub(r'\s*\%.*$', '', text, flags=re.M)
            # update _index with enum defintions
            self._index.update(find_enum_defs(text))


      # solver should be a list
      if type(solver) is not list:
        import shlex
        solver = shlex.split(solver)

      # run minizinc
      if verbose > 2: print(">>> model=\"\"\"\n{model}\n\"\"\"".format(model=model.strip()))
      if verbose > 2 and self.fmt: print(">>> fmt=\"{fmt}\"".format(fmt=self.fmt))
      if verbose > 2: print(">>> path=\"{path}\"".format(path=path))
      if verbose > 1: print(">>> solver={solver}".format(solver=solver))
      p = subprocess.Popen(solver + [path], stdout=subprocess.PIPE, bufsize=-1, cwd=mzn_dir, shell=use_shell)
      d = None
      ss = list()
      while True:
        s = p.stdout.readline()
        if not s: break
        # read output (in the appropriate encoding)
        s = s.decode(encoding).rstrip()
        ##print(">>> {s} <<<".format(s=s))
        if re.search(r'^-+$', s):
          #print("<{s}> end of record".format(s=s))
          # detect JSON mode
          if ss and ss[0] == '{': d = json.loads(' '.join(ss))
          if verbose > 0: print(">>> solution: " + str.join(' ', (k + "=" + repr(v) for (k, v) in d.items())))
          if result:
            yield Value(*(d[k] for k in Value._fields))
          else:
            yield d
          d = None
          ss = list()
        else:
          ss.append(s)
          #print(">>> {ss} <<<".format(ss=ss))
          m = re.search(r'^(\w+)\s*=\s*(.+)\s*;$', ' '.join(ss))
          #print(">>> {m} <<<".format(m=m))
          if m:
            (k, v) = (m.group(1), m.group(2))
            #print("<{ss}> {k} = >>> {v} <<<".format(s=s, k=k, v=v))
            if d is None: d = collections.OrderedDict()
            d[k] = parse(v, self)
            ss = list()

    finally:
      if create:
        # remove the temporary file
        os.unlink(path)

  def run(self, **args):
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
      fmt_ = fmt or self.fmt
      if fmt_:
        print(substitute(fmt_, s))
      else:
        print(str.join(' ', (k + "=" + repr(v) for (k, v) in s.items())))

  go = run

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

# emulate enums
# enum(["A", "B", "C"], "Name") = [[ int: A = 1; int: B = 2; int: C = 3; set of int: Name = 1..3; ]]
def enum(elements, name=None):
  lines = list("int: {x} = {i}".format(x=x, i=i) for (i, x) in enumerate(elements, start=1))
  if name is not None: lines.append("set of int: {name} = 1..{x}".format(name=name, x=len(elements)))
  return str.join(";\n", lines)

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
  return re.sub(r'{(\w+?)}', lambda m: _word(m.group(1), base), s)

# set the output format
def output(fmt):
  self = sys._getframe(1).f_locals['self']
  self.fmt = fmt
  return ''

# substitute ...
def substitute(s, d):
  fn = (d if callable(d) else (lambda x: str(d.get(x, '?'))))
  return re.sub(r'{(\w+)}', (lambda m: fn(m.group(1))), s)


# command line usage
if __name__ == "__main__":

  # this allows:
  #
  #   python3 minizinc.py [use_embed=1 ...] model.mzn
  #
  # to execute the given model, with embedded Python expressions evaluated

  argv = sys.argv[1:]
  if not argv: usage()
  args = dict(read_args(argv[:-1]))
  p = MiniZinc(argv[-1], **args)
  p.run()
