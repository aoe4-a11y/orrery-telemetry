"""Isolate user authority before collection imports dashboard or mail modules."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parent / 'tests'))
from user_home_isolation import isolated_user_environment

_ambient = dict(os.environ)
_ambient_tempdir = tempfile.tempdir
# macOS /var and /tmp are aliases. Fixture ownership paths must use the same
# canonical spelling as Seat.root, including before collection imports.
tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
_sandbox = tempfile.TemporaryDirectory(prefix='orrery-suite-')
_home = Path(_sandbox.name) / 'home'
_environment = isolated_user_environment(_home, dict(_ambient, TMPDIR=tempfile.tempdir))
os.environ.clear()
os.environ.update(_environment)


def pytest_unconfigure(config):
    os.environ.clear()
    os.environ.update(_ambient)
    _sandbox.cleanup()
    tempfile.tempdir = _ambient_tempdir
