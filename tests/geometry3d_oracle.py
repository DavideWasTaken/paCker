"""Test shim exposing the packaged 3D geometry oracle by file path."""
import hashlib
import importlib
import importlib.util
from pathlib import Path
import sys

_package = Path(__file__).resolve().parents[1] / 'python/packer_adapter'
_alias = '_captured_packer_adapter_' + hashlib.sha256(str(_package).encode()).hexdigest()[:16]
if _alias not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_alias, _package/'__init__.py',
                                                   submodule_search_locations=[str(_package)])
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_alias] = _module
    _spec.loader.exec_module(_module)
_geometry = importlib.import_module(_alias + '.geometry3d_oracle')
globals().update((name, value) for name, value in vars(_geometry).items()
                 if not name.startswith('__'))
