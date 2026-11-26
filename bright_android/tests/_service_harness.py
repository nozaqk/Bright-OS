"""Run the real Bright Android D-Bus service on the session bus, with a fake backend.

Used by test_dbus_integration.py and test_gui_runtime.py. Started as a
subprocess with the test's session bus address in the environment.

Only the Waydroid backend and launcher side effects are replaced. Authorization,
validation, the async operation machinery, signal emission, and config writes
are the real code.

Environment:
  BA_PROJECT_ROOT   project root to import bright_android from
  HOME              temporary home, so the config file is isolated
  FAKE_DELAY        seconds each slow backend call takes (default 0.5)
  FAKE_FAIL         comma list of: start, stop, init, install
  FAKE_DENY         "1" to deny every authorization check
  FAKE_LOG          file to append backend calls to, one per line
  FAKE_RUNNING      "1" to start with the runtime already running
"""

import os
import sys
import time

PROJECT_ROOT = os.environ["BA_PROJECT_ROOT"]
sys.path.insert(0, PROJECT_ROOT)

from bright_android.core import android_service as svc  # noqa: E402
from bright_android.core import waydroid_manager as wm  # noqa: E402
from bright_android.core import launcher_integration as li  # noqa: E402

DELAY = float(os.environ.get("FAKE_DELAY", "0.5"))
FAIL = set(filter(None, os.environ.get("FAKE_FAIL", "").split(",")))
DENY = os.environ.get("FAKE_DENY") == "1"
LOG = os.environ.get("FAKE_LOG")

STATE = {"running": os.environ.get("FAKE_RUNNING") == "1"}


def _log(entry: str):
    if LOG:
        with open(LOG, "a") as f:
            f.write(entry + "\n")


def _slow(name: str, progress_cb, messages):
    _log(name)
    for msg in messages:
        if progress_cb:
            progress_cb(msg)
        time.sleep(DELAY / max(1, len(messages)))


def fake_start_session(progress_cb=None):
    _slow("start_session", progress_cb, ["Starting Android container"])
    if "start" in FAIL:
        raise wm.WaydroidError("container failed to boot")
    STATE["running"] = True
    if progress_cb:
        progress_cb("Android is ready")
    return True


def fake_stop_session(progress_cb=None):
    _slow("stop_session", progress_cb, ["Stopping Android"])
    if "stop" in FAIL:
        raise wm.WaydroidError("stop failed")
    STATE["running"] = False
    return True


def fake_init(mode="auto", progress_cb=None):
    _slow("init", progress_cb, ["Downloading system image", "Initializing"])
    if "init" in FAIL:
        raise wm.WaydroidError("download failed: network unreachable")
    return True


def fake_install_apk(path, progress_cb=None):
    _slow("install_apk", progress_cb, ["Installing"])
    if "install" in FAIL:
        raise wm.WaydroidError("INSTALL_FAILED")
    return {"package": "com.example.app", "label": "Example", "path": path}


def fake_uninstall_app(package_name):
    _log("uninstall_app:" + package_name)
    return {"package": package_name}


wm.is_installed = lambda: True
wm.is_running = lambda: STATE["running"]
wm.get_status = lambda force_refresh=False: {
    "initialized": True,
    "running": STATE["running"],
    "session": "RUNNING" if STATE["running"] else "STOPPED",
    "details": {"waydroid_version": "fake"},
}
wm.list_apps = lambda: []
wm.start_session = fake_start_session
wm.stop_session = fake_stop_session
wm.init = fake_init
wm.install_apk = fake_install_apk
wm.uninstall_app = fake_uninstall_app
# launch_app stays real, so its package-name validation runs. Its is_running
# call is the fake above, and the launch itself fails because there is no waydroid.

li.sync_apps = lambda apps: None
li.remove_app_desktop_entry = lambda package: None
li.remove_all_android_entries = lambda: None

_original_check = svc._check_authorization


def _check(sender, action_id, bus=None, allow_same_user=False):
    if DENY:
        return False, "denied by test policy"
    return _original_check(sender, action_id, bus=bus, allow_same_user=allow_same_user)


svc._check_authorization = _check


def main():
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    name = dbus.service.BusName(svc.BUS_NAME, bus)  # noqa: F841 - keeps the name owned
    service = svc.BrightAndroidService(bus)
    loop = GLib.MainLoop()
    service._loop = loop
    print("READY", flush=True)
    loop.run()


if __name__ == "__main__":
    main()
