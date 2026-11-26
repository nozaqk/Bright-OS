#!/bin/bash
# =============================================================================
# Bright Desktop labwc session startup (experimental Phase 6.1 PoC)
#
# Launches labwc with Bright-OS-specific configuration. This script is
# invoked by the bright-labwc.desktop wayland-session file selected by
# the display manager (SDDM).
#
# The existing KWin session (bright-desktop-session.sh / bright.desktop)
# is UNTOUCHED. Users can fall back to it from the session menu.
# =============================================================================

set -e

# --- Session identity -----------------------------------------------------
export XDG_CURRENT_DESKTOP=Bright:labwc
export XDG_SESSION_TYPE=wayland
export DESKTOP_SESSION=bright-labwc

# --- Detect edition -------------------------------------------------------
EDITION=$(cat /etc/bright-os/edition 2>/dev/null || echo "home")

# --- Qt ------------------------------------------------------------------
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"
export QT_WAYLAND_DISABLE_WINDOWDECORATION=1
export QT_QPA_PLATFORMTHEME=qt6ct
export QT_STYLE_OVERRIDE=Fusion
export QT_AUTO_SCREEN_SCALE_FACTOR=1

# Lite edition: lighter rendering
if [ "$EDITION" = "lite" ]; then
    export QT_QUICK_CONTROLS_STYLE=Basic
    export QSG_RENDER_LOOP=basic
    export QT_AUTO_SCREEN_SCALE_FACTOR=0
fi

# --- GTK -----------------------------------------------------------------
if [ "$EDITION" = "lite" ]; then
    export GTK_THEME=Breeze
else
    export GTK_THEME=Breeze-Dark
fi
export GDK_BACKEND=wayland,x11

# --- Cursor --------------------------------------------------------------
export XCURSOR_THEME=breeze_cursors
export XCURSOR_SIZE=24
if [ "$EDITION" = "lite" ]; then
    export XCURSOR_SIZE=16
fi

# --- Audio ---------------------------------------------------------------
export PIPEWIRE_LATENCY=128/48000

# --- Tell the shell it's under labwc -------------------------------------
export BRIGHT_SHELL_COMPOSITOR=labwc

# --- XDG user dirs -------------------------------------------------------
if command -v xdg-user-dirs-update >/dev/null 2>&1; then
    xdg-user-dirs-update --force
fi

# --- GNOME keyring (if available; matches KWin session) ------------------
if command -v gnome-keyring-daemon >/dev/null 2>&1; then
    eval "$(gnome-keyring-daemon --start --components=secrets,ssh,pkcs11)"
    export SSH_AUTH_SOCK
fi

# --- Run labwc with our config directory ---------------------------------
# labwc searches XDG_CONFIG_DIRS; we prepend our shipped config so users
# can still override via ~/.config/labwc/. Labwc reads rc.xml, autostart,
# environment, menu.xml and themerc from the config directory.
LABWC_CONFIG_DIR="/usr/share/bright-os/labwc"

# Merge user XDG paths (respect XDG_CONFIG_HOME if set)
: "${XDG_CONFIG_HOME:=$HOME/.config}"
export XDG_CONFIG_DIRS="${LABWC_CONFIG_DIR}:${XDG_CONFIG_DIRS:-/etc/xdg}:/etc/xdg"

# Ensure XDG_RUNTIME_DIR exists (should already be set by PAM/systemd)
if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
    XDG_RUNTIME_DIR="/run/user/$(id -u)"
    export XDG_RUNTIME_DIR
fi
mkdir -p "$XDG_RUNTIME_DIR" 2>/dev/null || true

# If a user-provided rc.xml exists in XDG_CONFIG_HOME, labwc picks it up
# automatically; we don't override that. Only start labwc.
exec labwc --config-dir "${LABWC_CONFIG_DIR}"
