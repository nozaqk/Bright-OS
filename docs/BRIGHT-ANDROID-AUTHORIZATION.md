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
| InitializeRuntime | state change | no | `INIT` |
| StartRuntime | state change | no | `START` |
| StopRuntime | state change | no | `STOP` |
| InstallApk | state change | no | `INSTALL` |
| UninstallApp | state change | no | `UNINSTALL` |
| LaunchApp | session action | no | `LAUNCH` |
| SyncAppList | state change | no | `SYNC` |

The five signals (`OperationProgress`, `OperationComplete`, `AppInstalled`,
`AppRemoved`, `RuntimeStateChanged`) have no caller and are not gated.

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
  - Init, start, stop, restart, install, and uninstall run in a worker thread.
    The service runs `StartRuntime` and `StopRuntime` synchronously, so the
    service's main loop blocks for up to about 120 s while they run. Other D-Bus
    calls wait during that time.
  - `OperationProgress` is emitted only for `InitializeRuntime`. Other GUI
    operations show the operation name, not step-by-step progress.
  - Init waits for `OperationComplete`. That signal had a bad argument order
    (fixed in `f8fb510`), so before the fix no client received completion.
  - Tests: `bright_android/tests/test_gui_authorization.py` (static AST checks)
    and `bright_android/tests/test_service_client.py` (fake connections). Live
    D-Bus behavior and the GUI at runtime are not tested here. They need PyQt6
    and python3-dbus with the service running.
- The `bright-android --launch` and `--install-apk` CLI paths still use
  `waydroid_manager` directly, not D-Bus. They run as the invoking user, and they
  remain outside this authorization layer. Routing them through the service is
  open work.

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
- **The CLI paths (`--launch`, `--install-apk`) bypass D-Bus** (section 4).
- **Hung Polkit checks can deny service** (section 5).

