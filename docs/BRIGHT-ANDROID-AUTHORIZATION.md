# Bright Android: D-Bus Authorization Reference

This document describes exactly who can call the Bright Android D-Bus service,
what root can do, and which checks root does and does not bypass.

Source of truth: `bright_android/core/android_service.py` (`_get_caller_credentials`,
`_check_authorization`, `_polkit_consult`) and the `@method` definitions in
`BrightAndroidService`.

## 1. Decision order for every D-Bus method call

1. **D-Bus available.** If `dbus-python` is not importable, deny.
2. **Bus object present.** If no bus object is passed, deny.
3. **Sender present.** If the D-Bus sender is `None`, deny.
4. **Caller credentials.** Read the caller's PID and UID from the bus. If the
   lookup raises, or the PID is not a positive integer, or the UID is not a
   non-negative integer, deny.
5. **Root.** If UID is 0, allow. Polkit is not consulted for root. A
   state-changing root authorization is written to the log.
6. **Same user.** If UID differs from the service UID, deny.
7. **Read-only methods** (`allow_same_user=True`). Same-user callers are allowed
   without Polkit.
8. **State-changing methods.** Polkit must return an explicit
   `is_authorized() == True`. Everything else denies: challenge, not authorized,
   Polkit missing, authority error, check error, timeout, malformed response.

Steps 1–4 run before the root shortcut, so **root never skips sender identity or
credential validation.**

## 2. Method inventory

| Method | Gate | Same-user allowed without Polkit | Polkit action |
|---|---|---|---|
| GetVersion, GetCompatibilityReport, GetStatus, GetConfig | read | yes | `SYNC` |
| ListApps, ValidateApk, GetDiagnostics | read | yes | `SYNC` |
| SetConfig | state change | no | `SET_CONFIG` |
| SetConfigs | state change (batch) | no | `SET_CONFIG` (one check per batch) |
| InitializeRuntime | state change, async | no | `INIT` |
| StartRuntime | state change, async | no | `START` |
| StopRuntime | state change, async | no | `STOP` |
| InstallApk | state change | no | `INSTALL` |
| UninstallApp | state change | no | `UNINSTALL` |
| LaunchApp | session action | no | `LAUNCH` |
| SyncAppList | state change | no | `SYNC` |

The five signals (`OperationProgress`, `OperationComplete`, `AppInstalled`,
`AppRemoved`, `RuntimeStateChanged`) have no caller and are not gated.

### Asynchronous runtime operations

`InitializeRuntime`, `StartRuntime` and `StopRuntime` authorize the caller,
then return at once. The work runs in a background worker. Only one runtime
operation runs at a time. A second request while one is running is refused
with `org.bright_os.BrightAndroid.Busy`, and the running operation is not
disturbed.

- `OperationProgress(s operation, s message)` is emitted during the work.
- `OperationComplete(s operation, s message, b success)` is emitted when the
  work ends. `current_operation` is cleared before this signal, so a client
  that starts a new operation from its completion handler is not refused.
- `RuntimeStateChanged(b running)` is emitted after a successful start.

`InstallApk` is still synchronous. It blocks the main loop for up to 300 s.
Status queries wait during that time.

### Batch settings

`SetConfigs(a(ss) changes)` validates the whole batch before any write:

- Every key must be on the allowlist. Values are validated per key.
- Empty batches, batches over `MAX_BATCH` (32), malformed entries, and
  duplicate keys are rejected.
- Any invalid entry rejects the whole batch with `InvalidArgument`, and the
  error names the entry (`setting N: ...`). Nothing is written.
- One Polkit check covers the batch.
- The write is atomic: the temporary file is fsynced and then
  `os.replace`d over the config. The write is serialized by a lock. On any
  failure the previous config is kept and the call returns `WriteFailed`.

## 3. Root policy (decided)

Root keeps its bypass of Polkit. Root is trusted for administrative operations,
and the bypass is a deliberate, reviewed decision. It is not a gap.

Root still passes every other check: D-Bus sender identity (steps 2–3), PID/UID
credential validation (step 4), method-level input validation (including the
SetConfig allowlist), and the audit log for state changes.

## 3a. What root can do

Root is authorized for **all 15 gated methods above** (7 read-only and 8 that
change state). Concretely, root can:

- change any Bright Android configuration key (`SetConfig`),
- initialize, start and stop the Android container,
- install and uninstall APKs and apps, launch apps, and sync the app list.

**Why this is allowed:** root (UID 0) already has full control of the machine and
of the Android container's files and processes. Polkit's own default for UID 0 is
also "authorized", so skipping Polkit for root adds no new capability. Removing
the root shortcut would only block legitimate administration (for example,
recovering a broken container as root), and would require a password prompt
path that root cannot use over D-Bus.

**What root does not bypass:**

- sender identity checks (steps 2–3),
- credential validation (step 4), including a root caller with a missing bus,
  missing sender, or invalid PID,
- `dbus-python` availability (step 1),
- method-level input validation performed in the method body or in
  `waydroid_manager` (see section 5). This includes the SetConfig allowlist
  (`core/config_policy.py`), so root cannot write protected or unknown settings,
- the audit log: root state changes are logged at INFO with the action name.

## 4. Non-D-Bus callers

- **The desktop GUI** (`bright_android/gui.py`) performs every state change
  through the D-Bus service, using `bright_android/core/service_client.py`. It
  reads status and settings directly, through read-only `waydroid_manager`
  functions and `config.get_*` accessors. It never calls a state-changing
  `waydroid_manager` function, and never writes config. So the service's
  authorization covers every GUI state change, and the GUI runs without root.
  - Settings saves send only changed values. Each `SetConfig` is an
    `auth_admin_keep` Polkit action, so a change can prompt for admin auth. A
    failed save reports how many changes were applied.
  - Init, start, stop, restart, install, uninstall and launch run through
    `BrightAndroidClient`. Start, stop and init wait for `OperationComplete`
    (argument order `ssb`, see section 2). A `Busy` refusal is shown as a
    message, not a crash.
  - Restart is a client stop followed by a client start, in one worker.
  - Settings saves send one `SetConfigs` call with only the changed values.
    One admin prompt covers the batch. A refused batch changes nothing.
  - Each page keeps a reference to its worker thread until the thread has
    finished (`_release_worker`, which waits up to 5 s). Destroying a running
    `QThread` aborts the process.
  - Tests: `test_gui_authorization.py` (static AST checks) runs everywhere.
    `test_gui_runtime.py` runs the real PyQt6 pages (offscreen) against the
    real service over a session bus, under python3.12. The `_release_worker`
    change has no test that fails without it. The race it guards against did
    not reproduce in the test harness.
- The `bright-android --launch`, `--install-apk` and the wrapper's other
  state-changing paths go through the same D-Bus service as the GUI, via
  `bright_android/core/cli.py`. The CLI has no direct `waydroid_manager`
  state-changing calls (checked by AST tests in `test_cli.py`). Exit codes:
  0 ok, 1 failed, 3 denied, 4 service unavailable, 5 busy.

## 5. Polkit check limits

- **Timeout:** each Polkit check waits at most `POLKIT_CHECK_TIMEOUT_SECONDS`
  (60 s). After that the request is denied.
- **Concurrency cap:** at most `POLKIT_MAX_IN_FLIGHT` (4) checks run at once. A
  slot is acquired without blocking. When no slot is free, the request is denied
  at once with a "busy" reason, so the service stays responsive.
- **Hung checks are not cancelled.** Python cannot stop a thread blocked inside
  a native Polkit call. A timed-out check keeps its thread and its slot until
  the call returns, and its result is discarded. A hung Polkit daemon can
  therefore hold all slots, and state-changing calls are denied until a check
  returns. This is fail-closed, but it is a denial of service while Polkit is
  hung.
- **Late results are discarded.** Each request has its own state. A result that
  arrives after the timeout is never used, so it cannot authorize a request that
  was already denied.

## 6. Known gaps (not closed by this change)

- **AURA uses `Polkit.Authority.get_sync(None)`** (migrated from the deprecated
  `get()`). Failures still deny. Not verified against a live polkitd here.
- **Root authorization relies on Polkit's own default for UID 0.** This is my
  understanding of Polkit's behavior and is not verified in this sandbox.
- **Live D-Bus paths are untested in this environment:** the GUI client's
  signal wait for `InitializeRuntime`, the session-bus activation, and real
  Polkit prompts. Their tests use fakes.
- **Hung Polkit checks can deny service** (section 5).
- **Start, stop and init cannot be cancelled.** Python threads cannot be
  stopped, and there is no cancel method. A hung operation keeps the runtime
  busy until it returns, and later start or stop calls get `Busy`.
- **`InstallApk` is synchronous.** It blocks the service main loop for up to
  300 s, and status queries wait during that time.
- **AURA fails open without a bus.** `aura_core_service.py` returns allowed
  when `HAS_DBUS` is false or no bus is passed. Real service paths always pass
  a bus, but this is not fail-closed and is open for review.
- **Shell suites that byte-compile Python fail for non-root users.** The
  check in `tests/test-apps.sh` and related suites uses `py_compile` without
  a `cfile`, which writes into the source tree. Under a user who cannot write
  there, it reports "syntax error" for valid files.

