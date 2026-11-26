"""Shared test setup.

The real-bus tests (test_dbus_integration.py and test_gui_runtime.py) need one
session bus for the whole pytest run, because the client keeps a process-wide
connection. This starts dbus-daemon once, when the D-Bus stack is installed.
It does nothing when DBUS_SESSION_BUS_ADDRESS is already set, for example under
dbus-run-session.
"""

import os
import shutil
import subprocess

import pytest


def _stack_available() -> bool:
    try:
        import dbus  # noqa: F401
        import dbus.mainloop.glib  # noqa: F401
        from gi.repository import GLib  # noqa: F401
    except ImportError:
        return False
    return shutil.which("dbus-daemon") is not None


@pytest.fixture(scope="session", autouse=True)
def session_dbus_bus():
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS") or not _stack_available():
        yield
        return
    proc = subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1", "--nopidfile"],
        stdout=subprocess.PIPE, text=True)
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = proc.stdout.readline().strip()
    try:
        yield
    finally:
        proc.terminate()
        proc.wait(5)
