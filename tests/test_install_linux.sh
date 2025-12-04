#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR=""
cleanup() {
    if [[ -n "$TMP_DIR" ]]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT

test_preserves_user_groupings_on_update() {
    TMP_DIR="$(mktemp -d)"

    local payload_root="$TMP_DIR/payload"
    local src="$payload_root/EDMCModernOverlay"
    mkdir -p "$src"
    printf '{}' >"$src/overlay_groupings.json"

    local dest="$TMP_DIR/EDMCModernOverlay"
    mkdir -p "$dest"
    local user_file="$dest/overlay_groupings.user.json"
    printf '{"user":"keep"}' >"$user_file"

    MODERN_OVERLAY_INSTALLER_IMPORT=1 source "$SCRIPT_DIR/scripts/install_linux.sh"
    rsync_update_plugin "$src" "$dest"

    if [[ ! -f "$user_file" ]]; then
        echo "overlay_groupings.user.json was removed" >&2
        exit 1
    fi
    local content
    content="$(cat "$user_file")"
    if [[ "$content" != '{"user":"keep"}' ]]; then
        echo "overlay_groupings.user.json was altered: $content" >&2
        exit 1
    fi
}

test_preserves_user_groupings_on_update
