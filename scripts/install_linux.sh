#!/usr/bin/env bash

# install_linux.sh - helper to deploy EDMC Modern Overlay on Linux.

set -euo pipefail
IFS=$'\n\t'

readonly SCRIPT_PATH="${BASH_SOURCE[0]}"
readonly SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

find_release_root() {
    if [[ -d "${SCRIPT_DIR}/EDMC-ModernOverlay" ]]; then
        RELEASE_ROOT="${SCRIPT_DIR}"
    elif [[ -d "${SCRIPT_DIR}/../EDMC-ModernOverlay" ]]; then
        RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    else
        echo "❌ Could not find EDMC-ModernOverlay directory alongside install script." >&2
        exit 1
    fi
}

prompt_yes_no() {
    local prompt="${1:-Continue?}"
    local answer
    while true; do
        read -r -p "${prompt} [y/N]: " answer || return 1
        case "${answer}" in
            [Yy][Ee][Ss]|[Yy]) return 0 ;;
            [Nn][Oo]|[Nn]|'') return 1 ;;
            *) echo "Please answer yes or no." ;;
        esac
    done
}

require_command() {
    local cmd="$1"
    local pkg="${2:-$1}"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "❌ Required command '$cmd' not found. Please install '$pkg' and re-run." >&2
        exit 1
    fi
}

detect_plugins_dir() {
    local base="${XDG_DATA_HOME:-$HOME/.local/share}"
    local candidate="${base}/EDMarketConnector/plugins"
    if [[ -d "$candidate" ]]; then
        echo "✅ Detected EDMarketConnector plugins directory at '$candidate'."
        if prompt_yes_no "Use this directory?"; then
            PLUGIN_DIR="$(cd "$candidate" && pwd)"
            echo "✅ Using plugin directory: $PLUGIN_DIR"
            return
        fi
    else
        echo "⚠️  EDMarketConnector plugin directory not found at '$candidate'."
    fi

    while true; do
        read -r -p "Enter the path to your EDMarketConnector plugins directory: " candidate
        [[ -z "$candidate" ]] && { echo "❌ Path cannot be empty."; continue; }
        if [[ -d "$candidate" ]]; then
            PLUGIN_DIR="$(cd "$candidate" && pwd)"
            echo "✅ Using plugin directory: $PLUGIN_DIR"
            return
        fi
        echo "⚠️  Directory '$candidate' does not exist."
        if prompt_yes_no "Create this directory?"; then
            mkdir -p "$candidate"
            PLUGIN_DIR="$(cd "$candidate" && pwd)"
            echo "✅ Created and using plugin directory: $PLUGIN_DIR"
            return
        fi
        echo "Please provide a valid directory."
    done
}

ensure_edmc_not_running() {
    if command -v pgrep >/dev/null 2>&1 && pgrep -f "EDMarketConnector" >/dev/null 2>&1; then
        echo "⚠️  EDMarketConnector appears to be running."
        if prompt_yes_no "Quit EDMarketConnector and continue installation?"; then
            echo "Please close EDMarketConnector now, then press Enter to continue."
            read -r _
            if pgrep -f "EDMarketConnector" >/dev/null 2>&1; then
                echo "❌ EDMarketConnector is still running. Aborting." >&2
                exit 1
            fi
        else
            echo "❌ Installation requires EDMarketConnector to be closed. Aborting." >&2
            exit 1
        fi
    elif ! command -v pgrep >/dev/null 2>&1; then
        echo "⚠️  Cannot automatically detect if EDMarketConnector is running (pgrep not available)."
        echo "    Please ensure the application is closed before continuing."
        if ! prompt_yes_no "Continue with installation?"; then
            echo "❌ Installation aborted by user." >&2
            exit 1
        fi
    fi
}

disable_conflicting_plugins() {
    local conflicts=()
    shopt -s nullglob
    for entry in "$PLUGIN_DIR"/*; do
        local name="$(basename "$entry")"
        local lower="${name,,}"
        if [[ "$lower" == edmcoverlay* && "$lower" != *".disabled" ]]; then
            conflicts+=("$entry")
        fi
    done
    shopt -u nullglob

    if (( ${#conflicts[@]} == 0 )); then
        return
    fi

    echo "⚠️  Found legacy overlay plugins that conflict with Modern Overlay:"
    for path in "${conflicts[@]}"; do
        echo "   - $(basename "$path")"
    done
    if prompt_yes_no "Disable the legacy overlay plugin(s)?"; then
        for path in "${conflicts[@]}"; do
            local new_name="${path}.disabled"
            if [[ -e "$new_name" ]]; then
                echo "   - $(basename "$path") is already disabled."
                continue
            fi
            mv "$path" "$new_name"
            echo "   - Disabled $(basename "$path")."
        done
    else
        echo "❌ Cannot proceed while legacy overlay is enabled. Aborting." >&2
        exit 1
    fi
}

ensure_system_packages() {
    local packages=(
        libxcb-cursor0
        libxkbcommon-x11-0
    )

    if ! command -v dpkg-query >/dev/null 2>&1; then
        echo "⚠️  Skipping system package check because 'dpkg-query' is unavailable."
        echo "    Please ensure the following packages are installed manually: ${packages[*]}"
        return
    fi

    local missing=()
    for pkg in "${packages[@]}"; do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
            missing+=("$pkg")
        fi
    done

    if (( ${#missing[@]} == 0 )); then
        echo "✅ Required system packages already installed: ${packages[*]}"
        return
    fi

    echo "📦 Modern Overlay requires the following system packages:"
    printf '    %s\n' "${packages[@]}"
    echo "⚠️  Missing packages detected: ${missing[*]}"
    echo "    This step will run 'sudo apt-get update' followed by 'sudo apt-get install -y ${missing[*]}'."
    if ! prompt_yes_no "Install missing system packages now?"; then
        echo "❌ Installation cannot continue without required system packages." >&2
        exit 1
    fi

    require_command sudo
    echo "ℹ️  Running 'sudo apt-get update'..."
    sudo apt-get update
    echo "ℹ️  Running 'sudo apt-get install -y ${missing[*]}'..."
    sudo apt-get install -y "${missing[@]}"
}

maybe_install_wayland_deps() {
    echo "ℹ️  Wayland session support requires 'wmctrl' and 'x11-utils' for window tracking."
    if ! prompt_yes_no "Install Wayland helper packages now (sudo apt install wmctrl x11-utils)?"; then
        echo "ℹ️  Skipping Wayland/X11 helper packages."
        return
    fi

    require_command sudo
    echo "ℹ️  Running 'sudo apt install -y wmctrl x11-utils'..."
    sudo apt install -y wmctrl x11-utils
}

create_venv_and_install() {
    local target="$1"
    pushd "$target" >/dev/null
    if [[ ! -d overlay-client ]]; then
        echo "❌ Missing overlay-client directory in $target. Aborting." >&2
        popd >/dev/null
        exit 1
    fi

    if [[ ! -d overlay-client/.venv ]]; then
        echo "🐍 Creating Python virtual environment..."
        python3 -m venv overlay-client/.venv
    fi

    # shellcheck disable=SC1091
    source overlay-client/.venv/bin/activate
    echo "📦 Installing overlay client requirements..."
    pip install --upgrade pip >/dev/null
    pip install -r overlay-client/requirements.txt
    deactivate

    popd >/dev/null
}

copy_initial_install() {
    local src="$1"
    local plugin_root="$2"
    echo "📁 Copying Modern Overlay into plugins directory..."
    cp -a "$src" "$plugin_root"
    local target="${plugin_root}/$(basename "$src")"
    create_venv_and_install "$target"
}

rsync_update_plugin() {
    local src="$1"
    local dest="$2"
    if ! command -v rsync >/dev/null 2>&1; then
        echo "❌ rsync is required to update the plugin without overwriting the virtualenv." >&2
        exit 1
    fi

    local excludes=(
        "--exclude" "overlay-client/.venv/"
        "--exclude" "overlay-client/fonts/[Ee][Uu][Rr][Oo][Cc][Aa][Pp][Ss].ttf"
    )

    echo "🔄 Updating existing Modern Overlay installation..."
    rsync -av --delete "${excludes[@]}" "$src"/ "$dest"/
}

ensure_existing_install() {
    local dest="$1"
    if [[ ! -d "$dest/overlay-client/.venv" ]]; then
        echo "⚠️  Existing installation lacks a virtual environment. Creating one..."
        create_venv_and_install "$dest"
    fi
}

final_notes() {
    cat <<'EOF'

✅ Installation complete.
❗ install_eurocaps.sh was not run. Execute it separately if you wish to install the Eurocaps font.

EOF
}

main() {
    find_release_root
    require_command python3 "python3"
    detect_plugins_dir
    ensure_edmc_not_running
    ensure_system_packages
    maybe_install_wayland_deps
    disable_conflicting_plugins

    local src_dir="${RELEASE_ROOT}/EDMC-ModernOverlay"
    if [[ ! -d "$src_dir" ]]; then
        echo "❌ Source directory '$src_dir' not found. Aborting." >&2
        exit 1
    fi

    local dest_dir="${PLUGIN_DIR}/EDMC-ModernOverlay"

    if [[ ! -d "$dest_dir" ]]; then
        copy_initial_install "$src_dir" "$PLUGIN_DIR"
    else
        echo "⚠️  An existing installation was detected at '$dest_dir'."
        echo "    Plugin files will be replaced while preserving the existing overlay-client/.venv."
        if ! prompt_yes_no "Proceed with updating the installation?"; then
            echo "❌ Installation aborted by user to protect the existing virtual environment." >&2
            exit 1
        fi
        ensure_existing_install "$dest_dir"
        rsync_update_plugin "$src_dir" "$dest_dir"
    fi

    final_notes
    read -r -p $'Install finished, hit Enter to continue...'
}

main "$@"
