#!/bin/bash
# Bright OS Wine prefix management script
# Usage: wine-prefix-setup <prefix-name> [--win64|--win32]

set -e

PREFIX_NAME="${1:-default}"
ARCH="win64"

case "$2" in
    --win32) ARCH="win32" ;;
    --win64) ARCH="win64" ;;
esac

PREFIX_DIR="${HOME}/.wine-prefixes/${PREFIX_NAME}"

echo "Setting up Wine prefix '${PREFIX_NAME}' (${ARCH})..."
mkdir -p "$(dirname "$PREFIX_DIR")"

if [ -d "$PREFIX_DIR" ]; then
    echo "Prefix already exists: $PREFIX_DIR"
    WINEPREFIX="$PREFIX_DIR" WINEARCH="$ARCH" wineboot --update
else
    WINEPREFIX="$PREFIX_DIR" WINEARCH="$ARCH" wineboot --init
    echo "Wine prefix created: $PREFIX_DIR"
fi

echo ""
echo "To run a Windows application with this prefix:"
echo "  WINEPREFIX=\"$PREFIX_DIR\" wine /path/to/app.exe"
echo ""
echo "To install additional components:"
echo "  WINEPREFIX=\"$PREFIX_DIR\" winetricks -q dotnet48 dxvk vcrun2022"
