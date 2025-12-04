#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

test_preserves_user_groupings_on_update() {
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "$tmp_dir"' EXIT

    local payload_root="$tmp_dir/payload"
    local src="$payload_root/EDMCModernOverlay"
    mkdir -p "$src"
    printf '{}' >"$src/overlay_groupings.json"

    local dest="$tmp_dir/EDMCModernOverlay"
    mkdir -p "$dest"
    local user_file="$dest/overlay_groupings.user.json"
    printf '{"user":"keep"}' >"$user_file"

    export MODERN_OVERLAY_INSTALLER_IMPORT=1
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/scripts/install_linux.sh"
    unset MODERN_OVERLAY_INSTALLER_IMPORT
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
