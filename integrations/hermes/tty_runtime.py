"""Owned PTY transport: native input/display plus private diagnostic capture."""
import errno
import fcntl
import os
import pty
import select
import signal
import subprocess
import termios
import time
import tty


def _write(fd, data):
    while data:
        count = os.write(fd, data)
        if count <= 0:
            raise OSError('Incomplete terminal write')
        data = data[count:]


def run(command, *, cwd, env, log, started, stdin=0, stdout=1, deadline=None):
    """No default lifetime. deadline is an explicitly requested test bound.

    The child owns a new session/controlling terminal. The supervisor owns that
    process group and relays bytes, rather than redirecting native output to a
    regular file (which would silently select Hermes's one-shot mode).
    """
    if not os.isatty(stdin) or not os.isatty(stdout):
        raise ValueError('Interactive Hermes requires the owned pane TTY')
    master, slave = pty.openpty()
    previous = termios.tcgetattr(stdin)
    child = None
    prior_resize = signal.getsignal(signal.SIGWINCH)

    def resize(*_):
        size = fcntl.ioctl(stdin, termios.TIOCGWINSZ, b'\0' * 8)
        fcntl.ioctl(slave if child is None else master, termios.TIOCSWINSZ, size)
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGWINCH)
            except ProcessLookupError:
                pass

    def attach():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    try:
        resize()
        child = subprocess.Popen(command, cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave,
                                 preexec_fn=attach, close_fds=True)
        started(child)
        os.close(slave)
        slave = None
        tty.setraw(stdin)
        signal.signal(signal.SIGWINCH, resize)
        end = time.monotonic() + deadline if deadline is not None else None
        with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'wb', buffering=0) as capture:
            while True:
                if end is not None and time.monotonic() >= end:
                    raise subprocess.TimeoutExpired(command, deadline)
                available, _, _ = select.select([stdin, master], [], [], 0.1)
                if master in available:
                    try:
                        data = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        data = b''
                    if not data:
                        break
                    capture.write(data)
                    _write(stdout, data)
                if stdin in available:
                    data = os.read(stdin, 65536)
                    if not data:
                        os.killpg(child.pid, signal.SIGHUP)
                        break
                    _write(master, data)
                if child.poll() is not None and master not in available:
                    break
        return child.wait()
    finally:
        termios.tcsetattr(stdin, termios.TCSADRAIN, previous)
        signal.signal(signal.SIGWINCH, prior_resize)
        for fd in (master, slave):
            if fd is not None:
                os.close(fd)
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            except ProcessLookupError:
                child.wait()
