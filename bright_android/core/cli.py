"""Command-line operations for Bright Android.

Every state-changing operation goes through the D-Bus service, with
BrightAndroidClient, so the CLI gets the same authorization, validation and
audit as the GUI. This module does not call state-changing waydroid_manager
functions or write configuration. Read-only checks (is_running) and reads
(config.get_bool) stay direct.

Commands:
  bright-android --launch <package>     Launch an installed Android app
                                        (starts the runtime first if
                                        runtime/start_on_demand is true)
  bright-android --install-apk <path>   Install an APK

Exit codes:
  0  success
  1  usage error, or the operation failed
  3  the service refused the request (authorization denied)
  4  the service is not running or cannot be reached
  5  another runtime operation is already in progress
"""

import os
import sys
from typing import Callable, List, Optional, TextIO

from . import config as ba_config
from . import waydroid_manager
from .service_client import (
    AuthorizationDenied,
    BrightAndroidClient,
    BrightAndroidClientError,
    OperationFailed,
    RequestRejected,
    ServiceBusy,
    ServiceUnavailable,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_DENIED = 3
EXIT_UNAVAILABLE = 4
EXIT_BUSY = 5


def _exit_code_for(error: BrightAndroidClientError) -> int:
    if isinstance(error, AuthorizationDenied):
        return EXIT_DENIED
    if isinstance(error, ServiceUnavailable):
        return EXIT_UNAVAILABLE
    if isinstance(error, ServiceBusy):
        return EXIT_BUSY
    return EXIT_FAILED


def _usage_launch(err: TextIO) -> int:
    print("Usage: bright-android --launch <package-name>", file=err)
    return EXIT_FAILED


def _usage_install(err: TextIO) -> int:
    print("Usage: bright-android --install-apk <path>", file=err)
    return EXIT_FAILED


def _report(error: BrightAndroidClientError, err: TextIO, prefix: str) -> int:
    if isinstance(error, AuthorizationDenied):
        print(f"{prefix}: not authorized: {error}", file=err)
    else:
        print(f"{prefix}: {error}", file=err)
    return _exit_code_for(error)


def launch(package: Optional[str], client, is_running: Callable[[], bool],
           start_on_demand: Callable[[], bool], out: TextIO, err: TextIO) -> int:
    """Launch an app, starting the runtime first when the config allows it."""
    if not package:
        return _usage_launch(err)
    try:
        if not is_running():
            if not start_on_demand():
                print("Android runtime is not running.", file=err)
                return EXIT_FAILED
            print("Starting Android runtime...", file=err)
            client.start_runtime(progress_cb=lambda msg: print(msg, file=err))
        client.launch_app(package)
    except BrightAndroidClientError as e:
        return _report(e, err, "Error launching app")
    return EXIT_OK


def install(path: Optional[str], client, out: TextIO, err: TextIO) -> int:
    """Install an APK through the service. The path is made absolute first,
    because the service resolves paths in its own working directory."""
    if not path:
        return _usage_install(err)
    absolute = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(absolute):
        print(f"Error installing APK: no such file: {absolute}", file=err)
        return EXIT_FAILED
    try:
        client.install_apk(absolute)
    except BrightAndroidClientError as e:
        return _report(e, err, "Error installing APK")
    print(f"Installed: {os.path.basename(absolute)}", file=out)
    return EXIT_OK


def _option_value(argv: List[str], flag: str) -> Optional[str]:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    return argv[idx + 1] if idx + 1 < len(argv) else None


def run(argv: List[str], client_factory: Callable[[], object] = BrightAndroidClient,
        out: TextIO = sys.stdout, err: TextIO = sys.stderr) -> int:
    """Run one CLI command. Returns the process exit code."""
    if "--launch" in argv:
        return launch(
            _option_value(argv, "--launch"),
            client_factory(),
            is_running=waydroid_manager.is_running,
            start_on_demand=lambda: ba_config.get_bool("runtime", "start_on_demand", True),
            out=out,
            err=err,
        )
    if "--install-apk" in argv:
        return install(_option_value(argv, "--install-apk"), client_factory(), out, err)
    print("Usage: bright-android [--launch <package> | --install-apk <path>]", file=err)
    return EXIT_FAILED
