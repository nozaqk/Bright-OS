#!/bin/bash
# =============================================================================
# Bright Desktop labwc session startup (Phase 6.3 default compositor)
#
# Launches labwc (a wlroots-based Wayland compositor) with Bright-OS-specific
# configuration. Invoked by the bright.desktop wayland-session entry that
# greetd/gtkgreet, SDDM, or any other display manager can launch.
#
# User config overrides live in ~/.config/labwc/ and take precedence over the
# system-wide defaults at /usr/share/bright-os/labwc/.
# =============================================================================

set -e

# --- Session identity -----------------------------------------------------
export XDG_CURRENT_DESKTOP=Bright:labwc
export XDG_SESSION_TYPE=wayland
export DESKTOP_SESSION=bright-labwc

# --- Detect edition -------------------------------------------------------
EDITION=$(cat /etc/bright-os/edition 2>/dev/null || echo "home")

# --- Qt -------------------------------------------------------------------
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"
export QT_WAYLAND_DISABLE_WINDOWDECORATION=1
export QT_QPA_PLATFORMTHEME=qt6ct
export QT_STYLE_OVERRIDE=Fusion
export QT_AUTO_SCREEN_SCALE_FACTOR=1

# Low-resource rendering for Lite edition
if [ "$EDITION" = "lite" ]; then
    export QT_QUICK_CONTROLS_STYLE=Basic
    export QSG_RENDER_LOOP=basic
    export QT_AUTO_SCREEN_SCALE_FACTOR=0
fi

# --- GTK ------------------------------------------------------------------
export GDK_BACKEND=wayland,x11
export GTK_THEME=Breeze-Dark

# --- Cursor ---------------------------------------------------------------
export XCURSOR_THEME=breeze_cursors
export XCURSOR_SIZE=24
if [ "$EDITION" = "lite" ]; then
    export XCURSOR_SIZE=16
fi

# --- Audio (PipeWire is socket-activated by systemd --user) ---------------
export PIPEWIRE_LATENCY=128/48000

# --- Signal Bright Shell that we're on labwc ------------------------------
export BRIGHT_SHELL_COMPOSITOR=labwc

# --- XDG user dirs --------------------------------------------------------
if command -v xdg-user-dirs-update >/dev/null 2>&1; then
    xdg-user-dirs-update --force
fi

# --- GNOME keyring (if installed; for SSH/secrets) ------------------------
if command -v gnome-keyring-daemon >/dev/null 2>&1; then
    eval "$(gnome-keyring-daemon --start --components=secrets,ssh,pkcs11)"
    export SSH_AUTH_SOCK
fi

# --- Ensure XDG_RUNTIME_DIR exists (PAM/systemd usually set this) ---------
: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
export XDG_RUNTIME_DIR
mkdir -p "$XDG_RUNTIME_DIR" 2>/dev/null || true

# --- Start PipeWire user session if not already running -------------------
# In systemd user sessions these are socket-activated; under greetd/cage the
# systemd user instance is already started by PAM, but be safe.
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user import-environment >/dev/null 2>&1 || true
    systemctl --user start pipewire.service wireplumber.service >/dev/null 2>&1 || true
fi

# --- Labwc config directory (system-wide; ~/.config/labwc overrides) ------
LABWC_CONFIG_DIR="/usr/share/bright-os/labwc"
export XDG_CONFIG_DIRS="${LABWC_CONFIG_DIR}:${XDG_CONFIG_DIRS:-/etc/xdg}"

# Launch labwc. When labwc exits the session ends.
exec labwc --config-dir "${LABWC_CONFIG_DIR}"
