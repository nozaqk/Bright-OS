# labwc Proof of Concept (Phase 6.1) — Implementation Notes

This document describes the experimental labwc session added in Phase 6.1.

## What this PoC adds

A new **optional** Wayland session is registered:

- Display name: **"Bright Desktop (labwc experimental)"**
- Desktop file: `/usr/share/wayland-sessions/bright-labwc.desktop`
- Session script: `/usr/share/bright-os/bright-desktop-session-labwc.sh`
- labwc configuration directory: `/usr/share/bright-os/labwc/`
  - `rc.xml` — keybindings, mouse, theme, window rules
  - `menu.xml` — right-click desktop menu
  - `themerc` — window decoration colors
  - `environment` — session environment variables
  - `autostart` — launches the Bright shell + supporting daemons
- Optional package list (NOT in default ISO): `config/package-lists/labwc-experimental.list.chroot`

## What is unchanged

- The default Bright Desktop session (`bright.desktop`) is untouched and still
  uses KWin exactly as before.
- `core.list.chroot` does NOT include labwc or any new compositor packages.
- KWin and SDDM are still installed and bootable by default.
- The existing `/usr/bin/bright-desktop-shell` KWin wrapper is unchanged.
- The existing `bright-desktop-session.sh` (KWin path) is unchanged.
- AURA D-Bus activation (no WantedBy, D-Bus activated only) is unchanged.
- Bright Android session activation (`bright-android.service`) is unchanged.
- Shell.qml UI is unchanged; the same QML is loaded in both sessions.

## Shell integration

`bright-desktop-shell.py` was minimally modified to:

1. Accept a `--qml <path>` CLI argument so an alternate QML variant can be
   selected (e.g. the future `Shell-labwc.qml` for layer-shell surfaces).
2. When the environment variable `BRIGHT_SHELL_COMPOSITOR=labwc` is set,
   tag every shell window with app_id `bright-os-shell` via
   `QWindow.setDesktopFileName()`, which allows labwc window rules to
   match them. (Under KWin the app_id remains `bright-desktop-shell`.)

The labwc `rc.xml` defines a window rule for `bright-os-shell*` that:
- Disables server-side decorations (the shell paints its own panel/dock).
- Sets `skipTaskbar` and `skipWindowSwitcher` so shell surfaces don't
  appear in alt-tab.

## Autostart

The labwc `autostart` script starts (guarded by `command -v` so missing
optional packages don't break the session):

- PipeWire / WirePlumber / pipewire-pulse (audio)
- xdg-desktop-portal, xdg-desktop-portal-wlr, xdg-desktop-portal-gtk (file dialogs, screenshots)
- Polkit authentication agent (`polkit-gnome-authentication-agent-1`,
  falling back to `lxpolkit`/`lxqt-policykit-agent`)
- swayidle + swaylock for screen locking (optional)
- mako notification daemon (optional)
- kanshi output management (optional)
- nm-applet, blueman-applet, power manager applets
- `xdg-user-dirs-update`
- Finally, `exec`s the Bright Python shell with `--qml /usr/share/bright-os/Shell.qml`
  (or `/usr/share/bright-os/Shell-labwc.qml` if it exists in the future).

## Known PoC limitations (expected to resolve in later sub-phases)

1. **No layer-shell integration yet.** The existing Shell.qml uses
   `Qt.WindowStaysOnTopHint` / `Qt.WindowStaysOnBottomHint` and absolute
   (x,y) positioning. Under labwc these windows are regular xdg-shell
   toplevels; they will appear but:
   - Maximized windows may cover the panel (no exclusive zone).
   - The wallpaper will not be pinned to the background layer.
   - Overlay surfaces (launcher/notification/power menu) will appear as
     regular always-on-top windows and may not be exclusive-keyboard.
   Resolution: Phase 6.3 introduces `Shell-labwc.qml` using
   `qml6-module-org-kde-layershell` (`org.kde.layershell` attached
   properties) for proper panel/dock/background/overlay layers.
2. **No HiDPI scaling configuration is shipped.** kanshi config is left
   to the user; labwc uses the output's preferred mode by default.
3. **No screen locker configuration beyond invoking `swaylock`.** A
   proper lockscreen and idle config will be integrated with greetd in
   Phase 6.3+.
4. **No launcher Super-key integration yet.** The Super key alone is not
   intercepted by labwc; the panel button and Super+Return (terminal) /
   Super+e (files) work. Opening the launcher via Super requires layer-
   shell integration or a keybind that triggers the shell (possible via
   `bright-desktop-shell.py --show-launcher` in future).

## Compatibility check status

The following were validated statically (sub-phase 6.1):

| Check | Method | Status |
|---|---|---|
| New session files exist and are non-empty | test-labwc-poc.sh | PASS |
| XML well-formed (rc.xml, menu.xml) | xmllint via Python | PASS |
| Shell scripts syntax (bash -n) | test-labwc-poc.sh | PASS |
| Python syntax (bright-desktop-shell.py) | py_compile | PASS |
| KWin session file intact | diff, grep | PASS |
| core.list.chroot does not include labwc | grep | PASS |
| Source / packaged copies in sync | diff | PASS |
| Existing Python + shell tests (592+ tests) | unittest + all shell suites | PASS |
| CI runs the new suite automatically | wildcard `tests/test-*.sh` | yes |

The following require QEMU/hardware testing (NOT performed in 6.1 sandbox
which has no KVM/QEMU/labwc/Wayland):

1. labwc starts successfully from SDDM.
2. Bright desktop shell appears under labwc.
3. Panel, dock and launcher are visible and clickable.
4. Wayland-native apps launch (e.g. foot, alacritty, qt6ct).
5. XWayland apps launch (e.g. firefox-esr, libreoffice).
6. Window focus, movement (Alt+drag), resizing (Alt+right-drag), alt-tab
   switching work.
7. mako notifications appear.
8. Lock via Super-L / Alt-L, logout via Ctrl+Alt+Del safely.
9. Polkit authentication dialogs appear on top.
10. AURA can be activated via D-Bus and its GUI dialogs render.
11. Bright Android session activates and renders its window.
12. Reboot to the KWin session works (selectable from SDDM).

## How to test on a Debian 13 Trixie development machine

```sh
# Install experimental packages
sudo apt install labwc layer-shell-qt qml6-module-org-kde-layershell \
    xdg-desktop-portal-wlr mako-notifier swaylock swayidle kanshi grim slurp \
    polkit-gnome-agent-1

# (Re)build the ISO or install the configs into your system:
sudo cp -r config/includes.chroot/usr/share/bright-os/labwc /usr/share/bright-os/
sudo cp config/includes.chroot/usr/share/bright-os/bright-desktop-session-labwc.sh \
       /usr/share/bright-os/
sudo cp config/includes.chroot/usr/share/wayland-sessions/bright-labwc.desktop \
       /usr/share/wayland-sessions/
sudo chmod +x /usr/share/bright-os/bright-desktop-session-labwc.sh
sudo chmod +x /usr/share/bright-os/labwc/autostart
# Copy the shell too if testing locally (or install the .deb):
sudo cp config/includes.chroot/usr/share/bright-os/bright-desktop-shell.py \
       /usr/share/bright-os/
sudo cp desktop/shell/Shell.qml /usr/share/bright-os/
sudo cp -r desktop/shell/design /usr/share/bright-os/
sudo cp -r desktop/shell/profiles /usr/share/bright-os/
```

Then log out and select "Bright Desktop (labwc experimental)" from the
SDDM session menu.

## Rollback

To revert this sub-phase, simply do not install the labwc packages and
do not select the experimental session. No existing configuration is
modified; removing the new files is sufficient:

```sh
sudo rm -f /usr/share/wayland-sessions/bright-labwc.desktop
sudo rm -rf /usr/share/bright-os/labwc
sudo rm -f /usr/share/bright-os/bright-desktop-session-labwc.sh
```

The default KWin session remains fully functional at all times.
