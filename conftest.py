"""Isolate user authority before collection imports dashboard or mail modules."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parent / 'tests'))
from user_home_isolation import isolated_user_environment

_ambient = dict(os.environ)
_sandbox = tempfile.TemporaryDirectory(prefix='orrery-suite-')
_home = Path(_sandbox.name) / 'home'
_environment = isolated_user_environment(_home, _ambient)
os.environ.clear()
os.environ.update(_environment)


def pytest_unconfigure(config):
    os.environ.clear()
    os.environ.update(_ambient)
    _sandbox.cleanup()
