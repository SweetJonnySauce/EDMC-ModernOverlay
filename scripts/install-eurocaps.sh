#!/usr/bin/env bash
# Helper script to download the Eurocaps cockpit font into the Modern Overlay plugin.
# Usage: ./install-eurocaps.sh [path-to-EDMC-ModernOverlay]

set -euo pipefail

FONT_URL="https://raw.githubusercontent.com/inorton/EDMCOverlay/master/EDMCOverlay/EDMCOverlay/EUROCAPS.TTF"
DEFAULT_PLUGIN_DIR="${HOME}/.local/share/EDMarketConnector/plugins/EDMC-ModernOverlay"
PLUGIN_DIR="${1:-$DEFAULT_PLUGIN_DIR}"
FONT_DIR="${PLUGIN_DIR}/overlay-client/fonts"
TARGET_FONT="${FONT_DIR}/Eurocaps.ttf"
PREFERRED_LIST="${FONT_DIR}/preferred_fonts.txt"

echo "Using plugin directory: ${PLUGIN_DIR}"

if [[ ! -d "${FONT_DIR}" ]]; then
    echo "Error: ${FONT_DIR} not found. Provide the path to your EDMC-ModernOverlay plugin." >&2
    exit 1
fi

TMP_FONT="$(mktemp)"
cleanup() {
    rm -f "${TMP_FONT}"
}
trap cleanup EXIT

download_font() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "${FONT_URL}" -o "${TMP_FONT}"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "${TMP_FONT}" "${FONT_URL}"
    else
        echo "Error: Neither curl nor wget is available for download." >&2
        exit 1
    fi
}

echo "Downloading Eurocaps.ttf from ${FONT_URL}..."
download_font

if [[ ! -s "${TMP_FONT}" ]]; then
    echo "Error: Download failed or produced an empty file." >&2
    exit 1
fi

install -m 644 "${TMP_FONT}" "${TARGET_FONT}"
echo "Installed Eurocaps.ttf to ${TARGET_FONT}"

if [[ -f "${PREFERRED_LIST}" ]]; then
    if ! grep -iq "^Eurocaps\.ttf$" "${PREFERRED_LIST}"; then
        echo "Eurocaps.ttf" >> "${PREFERRED_LIST}"
        echo "Added Eurocaps.ttf to preferred_fonts.txt"
    else
        echo "Eurocaps.ttf already listed in preferred_fonts.txt"
    fi
else
    echo "Warning: preferred_fonts.txt not found. The overlay will still discover the font automatically."
fi

echo "Done. Restart the overlay client to pick up the new font."
