#!/bin/bash
# Bright Desktop session startup script
# Sets required environment variables and launches KWin with our shell
# Supports all three editions: home, developer, lite

# Set XDG current desktop for XDG integration
export XDG_CURRENT_DESKTOP=Bright
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
export DESKTOP_SESSION=bright

# Detect edition
EDITION=$(cat /etc/bright-os/edition 2>/dev/null || echo "home")

# Qt configuration
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"
export QT_WAYLAND_DISABLE_WINDOWDECORATION=1
export QT_QPA_PLATFORMTHEME=qt6ct
export QT_STYLE_OVERRIDE=Fusion
export QT_AUTO_SCREEN_SCALE_FACTOR=1

# Lite edition: reduce Qt rendering overhead
if [ "$EDITION" = "lite" ]; then
    export QT_QUICK_CONTROLS_STYLE=Basic
    export QSG_RENDER_LOOP=basic
    export QT_AUTO_SCREEN_SCALE_FACTOR=0
    # Use qt5ct for LXQt compatibility when Bright shell not available
    if [ -z "$QT_QPA_PLATFORMTHEME" ]; then
        export QT_QPA_PLATFORMTHEME=qt5ct
    fi
fi

# GTK configuration for consistent theming (shared across all editions)
if [ "$EDITION" = "lite" ]; then
    # Lite: use a lighter GTK theme
    export GTK_THEME=Breeze
else
    export GTK_THEME=Breeze-Dark
fi
export GTK2_RC_FILES=/usr/share/themes/Breeze-Dark/gtk-2.0/gtkrc
export XDG_CURRENT_DESKTOP=Bright:KDE

# Sound server
export PIPEWIRE_LATENCY=128/48000

# Default cursor theme (shared across all editions)
export XCURSOR_THEME=breeze_cursors
export XCURSOR_SIZE=24

# Lite: smaller cursor for low-res displays
if [ "$EDITION" = "lite" ]; then
    export XCURSOR_SIZE=16
fi

# User directories
[ -x /usr/bin/xdg-user-dirs-update ] && xdg-user-dirs-update --force

# Start keyring if available
if command -v gnome-keyring-daemon &>/dev/null; then
    eval "$(gnome-keyring-daemon --start --components=secrets,ssh,pkcs11)"
    export SSH_AUTH_SOCK
fi

# Lite edition: start picom compositor with lightweight settings if on X11
if [ "$EDITION" = "lite" ] && [ "$XDG_SESSION_TYPE" = "x11" ]; then
    if command -v picom &>/dev/null; then
        picom --config /dev/null --backend glx --vsync --no-vsync --shadow --no-fading-openclose &
        PICOM_PID=$!
    fi
fi

# Launch KWin as Wayland compositor with our shell embedded
# If kwin_wayland is not available (e.g. X11 fallback, Lite), run shell directly
if command -v kwin_wayland &> /dev/null && [ "$XDG_SESSION_TYPE" = "wayland" ] && [ "$EDITION" != "lite" ]; then
    # Home/Developer: full KWin with effects
    exec kwin_wayland --no-lockscreen --no-global-shortcuts --exit-with-session=/usr/share/bright-os/bright-desktop-shell.py
elif command -v kwin_wayland &> /dev/null && [ "$XDG_SESSION_TYPE" = "wayland" ] && [ "$EDITION" = "lite" ]; then
    # Lite: KWin with effects disabled
    exec kwin_wayland --no-lockscreen --no-global-shortcuts --no-kactivities --no-global-shortcuts \
        --exit-with-session=/usr/share/bright-os/bright-desktop-shell.py
else
    # Fallback: run shell directly on existing X/Wayland session
    # Lite edition: use openbox as WM if available
    if [ "$EDITION" = "lite" ] && command -v openbox &>/dev/null && [ "$XDG_SESSION_TYPE" = "x11" ]; then
        openbox --replace &
    fi
    exec /usr/share/bright-os/bright-desktop-shell.py
fi
