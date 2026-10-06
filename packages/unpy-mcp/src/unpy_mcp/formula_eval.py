"""Compatibility shim — the formula interpreter now lives in unpy-core.

Every symbol is re-exported from `unpy.formula_eval`, including the
module-private cache hooks some perf tests monkey-patch. New code should
import from there directly.
"""

import importlib as _importlib
import sys as _sys

_core = _importlib.import_module("unpy.formula_eval")
_sys.modules[__name__].__dict__.update(_core.__dict__)