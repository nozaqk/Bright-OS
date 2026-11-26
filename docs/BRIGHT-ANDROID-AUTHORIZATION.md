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

## 3. What root can do

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
  `waydroid_manager` (see section 5),
- the audit log: root state changes are logged at INFO with the action name.

## 4. Non-D-Bus callers

- **The desktop GUI** (`bright_android/gui.py`) does not call the D-Bus service.
  It imports `waydroid_manager` and runs as the logged-in user, so it bypasses
  this authorization layer entirely. It has the same privileges as that user, not
  as root. Changing this requires moving GUI actions behind the D-Bus service;
  that is a design decision and is not done here.
- The `bright-android --launch` and `--install-apk` CLI paths also use
  `waydroid_manager` directly, not D-Bus.

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

- **SetConfig accepts any `section/key`.** No allowlist exists. Any caller that
  passes authorization (including root) can write any key in the Bright Android
  config file. Needs an allowlist of settable keys.
- **Polkit call uses the deprecated `Polkit.Authority.get()`** in AURA
  (`aura/core/aura_core_service.py`). It works, but the replacement is
  `get_sync`. Migration is a low-priority cleanup.
- **Root authorization relies on Polkit's own default for UID 0.** This is my
  understanding of Polkit's behavior and is not verified in this sandbox.

