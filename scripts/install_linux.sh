#!/usr/bin/env bash

# install_linux.sh - helper to deploy EDMC Modern Overlay on Linux.

set -euo pipefail
IFS=$'\n\t'

readonly SCRIPT_PATH="${BASH_SOURCE[0]}"
readonly SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
readonly MATRIX_FILE="${SCRIPT_DIR}/install_matrix.json"
readonly EUROCAPS_FONT_URL="https://raw.githubusercontent.com/inorton/EDMCOverlay/master/EDMCOverlay/EDMCOverlay/EUROCAPS.TTF"
readonly EUROCAPS_FONT_NAME="Eurocaps.ttf"

ASSUME_YES=false
DRY_RUN=false
PLUGIN_DIR_OVERRIDE=""

declare -a POSITIONAL_ARGS=()
declare -a MATRIX_STANDARD_PATHS=()
declare -a MATRIX_FLATPAK_PATHS=()
MATRIX_PATHS_LOADED=0

PROFILE_OVERRIDE=""
PROFILE_SELECTED=0
PROFILE_SOURCE=""
PROFILE_ID=""
PROFILE_LABEL=""
declare -a PKG_UPDATE_CMD=()
declare -a PKG_INSTALL_CMD=()
declare -a PROFILE_PACKAGES_CORE=()
declare -a PROFILE_PACKAGES_QT=()
declare -a PROFILE_PACKAGES_WAYLAND=()
PKG_UPDATE_COMPLETED=0
PACKAGE_MANAGER_KIND=""
PACKAGE_STATUS_CHECK_SUPPORTED=0
DISPLAY_STACK_DETECTED=""
declare -a PACKAGES_TO_INSTALL=()
declare -a PACKAGES_TO_UPGRADE=()
declare -a PACKAGES_ALREADY_OK=()
declare -A PACKAGE_STATUS_DETAILS=()

print_usage() {
    cat <<'EOF'
Usage: install_linux.sh [options]

Options:
  -y, --yes, --assume-yes   Automatically answer "yes" to prompts.
      --dry-run             Show the actions that would be taken without making changes.
      --profile <id>        Force a distro profile from scripts/install_matrix.json (e.g. debian, fedora).
      --help                Show this message.

You may optionally supply a single positional argument that points at the EDMC plugins directory.
EOF
}

parse_args() {
    POSITIONAL_ARGS=()
    while (($# > 0)); do
        case "$1" in
            -y|--yes|--assume-yes)
                ASSUME_YES=true
                ;;
            --dry-run)
                DRY_RUN=true
                ;;
            --profile)
                shift || { echo "❌ --profile requires an argument." >&2; exit 1; }
                PROFILE_OVERRIDE="${1,,}"
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            --)
                shift
                break
                ;;
            -*)
                echo "❌ Unknown option: $1" >&2
                print_usage
                exit 1
                ;;
            *)
                POSITIONAL_ARGS+=("$1")
                ;;
        esac
        shift || break
    done
    while (($# > 0)); do
        POSITIONAL_ARGS+=("$1")
        shift
    done
    if ((${#POSITIONAL_ARGS[@]} > 1)); then
        echo "❌ Unexpected positional arguments: ${POSITIONAL_ARGS[*]}" >&2
        exit 1
    fi
    if ((${#POSITIONAL_ARGS[@]} == 1)); then
        PLUGIN_DIR_OVERRIDE="${POSITIONAL_ARGS[0]}"
    fi
}

format_command() {
    local formatted=""
    local part
    for part in "$@"; do
        formatted+=" $(printf '%q' "$part")"
    done
    printf '%s' "${formatted# }"
}

matrix_helper() {
    local mode="$1"
    shift
    if [[ ! -f "$MATRIX_FILE" ]]; then
        echo "❌ Manifest file '$MATRIX_FILE' not found. Re-download the release archive." >&2
        exit 1
    fi
    python3 - "$MATRIX_FILE" "$mode" "$@" <<'PY'
import json
import shlex
import sys

def emit_array(name, items):
    if not items:
        print(f"{name}=()")
        return
    joined = " ".join(shlex.quote(str(item)) for item in items)
    print(f"{name}=({joined})")

def emit_profile(profile):
    label = profile.get("label") or profile.get("id") or "Unknown"
    print("PROFILE_FOUND=1")
    print(f"PROFILE_ID={shlex.quote(profile.get('id', 'unknown'))}")
    print(f"PROFILE_LABEL={shlex.quote(label)}")
    pkg = profile.get("pkg_manager") or {}
    emit_array("PKG_UPDATE_CMD", pkg.get("update") or [])
    emit_array("PKG_INSTALL_CMD", pkg.get("install") or [])
    packages = profile.get("packages") or {}
    emit_array("PROFILE_PACKAGES_CORE", packages.get("core") or [])
    emit_array("PROFILE_PACKAGES_QT", packages.get("qt") or [])
    emit_array("PROFILE_PACKAGES_WAYLAND", packages.get("wayland") or [])

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
distros = data.get("distros", [])
mode = sys.argv[2]

def normalise(values):
    return [str(value).lower() for value in values]

if mode == "paths":
    plugin_paths = data.get("plugin_paths", {})
    emit_array("MATRIX_STANDARD_PATHS", plugin_paths.get("standard") or [])
    emit_array("MATRIX_FLATPAK_PATHS", plugin_paths.get("flatpak") or [])
elif mode == "match":
    os_id = sys.argv[3].lower() if len(sys.argv) > 3 else ""
    like_raw = sys.argv[4] if len(sys.argv) > 4 else ""
    like_values = [chunk.lower() for chunk in like_raw.split(",") if chunk]
    for profile in distros:
        match = profile.get("match") or {}
        ids = normalise(match.get("ids") or [])
        likes = normalise(match.get("id_like") or [])
        if os_id and os_id in ids:
            emit_profile(profile)
            break
        if os_id and os_id in likes:
            emit_profile(profile)
            break
        if like_values and ids and any(value in ids for value in like_values):
            emit_profile(profile)
            break
        if like_values and likes and any(value in likes for value in like_values):
            emit_profile(profile)
            break
elif mode == "list":
    for index, profile in enumerate(distros, start=1):
        pid = profile.get("id") or f"profile-{index}"
        label = profile.get("label") or pid
        print(f"{index}|{pid}|{label}")
elif mode == "by-id":
    target = sys.argv[3].lower()
    for profile in distros:
        pid = (profile.get("id") or "").lower()
        if pid == target:
            emit_profile(profile)
            break
else:
    raise SystemExit(f"Unknown matrix helper mode: {mode}")
PY
}

load_plugin_path_templates() {
    if (( MATRIX_PATHS_LOADED )); then
        return
    fi
    eval "$(matrix_helper paths)"
    MATRIX_PATHS_LOADED=1
}

select_custom_profile() {
    PROFILE_SELECTED=1
    PROFILE_SOURCE="manual-skip"
    PROFILE_ID="custom"
    PROFILE_LABEL="Custom (manual dependency management)"
    PKG_UPDATE_CMD=()
    PKG_INSTALL_CMD=()
    PROFILE_PACKAGES_CORE=()
    PROFILE_PACKAGES_QT=()
    PROFILE_PACKAGES_WAYLAND=()
}

select_profile_by_id() {
    local profile_id="${1,,}"
    if [[ -z "$profile_id" ]]; then
        return 1
    fi
    if [[ "$profile_id" == "skip" || "$profile_id" == "none" ]]; then
        select_custom_profile
        return 0
    fi
    local output
    output="$(matrix_helper by-id "$profile_id")"
    if [[ -z "$output" ]]; then
        return 1
    fi
    eval "$output"
    if [[ "${PROFILE_FOUND:-0}" -eq 1 ]]; then
        PROFILE_SELECTED=1
        PROFILE_SOURCE="manual"
        return 0
    fi
    return 1
}

ensure_distro_profile() {
    if (( PROFILE_SELECTED )); then
        return
    fi
    if [[ -n "$PROFILE_OVERRIDE" ]]; then
        if ! select_profile_by_id "$PROFILE_OVERRIDE"; then
            echo "❌ Unknown distro profile '$PROFILE_OVERRIDE'. Check scripts/install_matrix.json." >&2
            exit 1
        fi
        return
    fi
    auto_detect_profile
}

auto_detect_profile() {
    local os_id="unknown"
    local os_like=""
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        os_id="${ID:-unknown}"
        os_like="${ID_LIKE:-}"
    fi
    local like_csv="${os_like// /,}"
    local output
    output="$(matrix_helper match "${os_id,,}" "${like_csv,,}")"
    if [[ -n "$output" ]]; then
        eval "$output"
        if [[ "${PROFILE_FOUND:-0}" -eq 1 ]]; then
            PROFILE_SELECTED=1
            PROFILE_SOURCE="auto"
            return
        fi
    fi
    echo "⚠️  Could not automatically determine distro profile for ID='${os_id}' (ID_LIKE='${os_like}')."
    if [[ "$ASSUME_YES" == true ]]; then
        echo "❌ Non-interactive mode requires --profile <id> when auto-detection fails." >&2
        exit 1
    fi
    prompt_manual_profile_selection
}

prompt_manual_profile_selection() {
    local entries
    entries="$(matrix_helper list)"
    if [[ -z "$entries" ]]; then
        echo "❌ scripts/install_matrix.json does not define any distro profiles." >&2
        exit 1
    fi
    echo "Available distro profiles:"
    echo " 0) Skip automatic package installation (manage dependencies yourself)"
    local -a profile_ids=()
    local -a profile_labels=()
    local -a profile_numbers=()
    local line
    while IFS='|' read -r number ident label; do
        profile_ids+=("$ident")
        profile_labels+=("$label")
        profile_numbers+=("$number")
        printf ' %s) %s (%s)\n' "$number" "$label" "$ident"
    done <<< "$entries"
    local choice
    while true; do
        read -r -p "Select a profile [0-${#profile_ids[@]}]: " choice
        choice="${choice,,}"
        if [[ -z "$choice" ]]; then
            continue
        fi
        if [[ "$choice" == "0" || "$choice" == "skip" || "$choice" == "none" ]]; then
            select_custom_profile
            return
        fi
        local idx
        for idx in "${!profile_ids[@]}"; do
            if [[ "$choice" == "${profile_numbers[idx]}" || "$choice" == "${profile_ids[idx],,}" ]]; then
                if select_profile_by_id "${profile_ids[idx]}"; then
                    return
                fi
                echo "❌ Failed to load profile '${profile_ids[idx]}'. Check scripts/install_matrix.json." >&2
                exit 1
            fi
        done
        echo "Unrecognised selection '$choice'."
    done
}

run_package_install() {
    local label="$1"
    shift
    local packages=("$@")
    if ((${#packages[@]} == 0)); then
        echo "ℹ️  No packages defined for $label on profile '$PROFILE_LABEL'."
        return
    fi
    if ((${#PKG_INSTALL_CMD[@]} == 0)); then
        echo "❌ Package install command is undefined for profile '$PROFILE_LABEL'. Please install manually: ${packages[*]}" >&2
        exit 1
    fi
    if (( ! PKG_UPDATE_COMPLETED )) && ((${#PKG_UPDATE_CMD[@]} > 0)); then
        echo "ℹ️  Updating package index before installing ${label}..."
        if [[ "$DRY_RUN" == true ]]; then
            echo "📝 [dry-run] $(format_command "${PKG_UPDATE_CMD[@]}")"
        else
            "${PKG_UPDATE_CMD[@]}"
        fi
        PKG_UPDATE_COMPLETED=1
    fi
    echo "ℹ️  Installing ${label} via ${PKG_INSTALL_CMD[1]:-package manager}..."
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] $(format_command "${PKG_INSTALL_CMD[@]}" "${packages[@]}")"
    else
        "${PKG_INSTALL_CMD[@]}" "${packages[@]}"
    fi
}

reset_package_status_tracking() {
    PACKAGES_TO_INSTALL=()
    PACKAGES_TO_UPGRADE=()
    PACKAGES_ALREADY_OK=()
    PACKAGE_STATUS_DETAILS=()
}

get_pkg_manager_binary() {
    local part
    for part in "${PKG_INSTALL_CMD[@]}"; do
        case "$part" in
            sudo|doas|pkexec) continue ;;
            *)
                printf '%s' "$part"
                return
                ;;
        esac
    done
}

detect_package_manager_kind() {
    if [[ -n "$PACKAGE_MANAGER_KIND" ]]; then
        printf '%s' "$PACKAGE_MANAGER_KIND"
        return
    fi
    local binary
    binary="$(get_pkg_manager_binary)"
    case "$binary" in
        apt|apt-get) PACKAGE_MANAGER_KIND="apt" ;;
        dnf|yum|microdnf) PACKAGE_MANAGER_KIND="dnf" ;;
        zypper) PACKAGE_MANAGER_KIND="zypper" ;;
        pacman) PACKAGE_MANAGER_KIND="pacman" ;;
        *) PACKAGE_MANAGER_KIND="" ;;
    esac
    printf '%s' "$PACKAGE_MANAGER_KIND"
}

classify_packages_for_apt() {
    local pkg status_line status installed_version candidate
    for pkg in "$@"; do
        if ! status_line="$(dpkg-query -W -f='${db:Status-Abbrev}\t${Version}\n' "$pkg" 2>/dev/null)"; then
            PACKAGES_TO_INSTALL+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="not installed"
            continue
        fi
        IFS=$'\t' read -r status installed_version <<<"$status_line"
        if [[ "${status}" != ii* || -z "$installed_version" ]]; then
            PACKAGES_TO_INSTALL+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="not installed"
            continue
        fi
        candidate="$(apt-cache policy "$pkg" 2>/dev/null | awk '/Candidate:/ {print $2; exit}')"
        if [[ -z "$candidate" || "$candidate" == "(none)" ]]; then
            candidate="$installed_version"
        fi
        if [[ -n "$candidate" && -n "$installed_version" ]] && dpkg --compare-versions "$candidate" gt "$installed_version"; then
            PACKAGES_TO_UPGRADE+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="installed ${installed_version} → candidate ${candidate}"
        else
            PACKAGES_ALREADY_OK+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="installed ${installed_version}"
        fi
    done
}

classify_package_statuses() {
    reset_package_status_tracking
    local manager_kind
    manager_kind="$(detect_package_manager_kind)"
    if [[ -z "$manager_kind" ]]; then
        PACKAGE_STATUS_CHECK_SUPPORTED=0
        PACKAGES_TO_INSTALL=("$@")
        for pkg in "$@"; do
            PACKAGE_STATUS_DETAILS["$pkg"]="status check unavailable (unknown package manager)"
        done
        return
    fi

    case "$manager_kind" in
        apt)
            PACKAGE_STATUS_CHECK_SUPPORTED=1
            classify_packages_for_apt "$@"
            ;;
        *)
            PACKAGE_STATUS_CHECK_SUPPORTED=0
            PACKAGES_TO_INSTALL=("$@")
            for pkg in "$@"; do
                PACKAGE_STATUS_DETAILS["$pkg"]="status check unsupported for manager '${manager_kind}'"
            done
            ;;
    esac
}

detect_display_stack() {
    if [[ -n "$DISPLAY_STACK_DETECTED" ]]; then
        printf '%s' "$DISPLAY_STACK_DETECTED"
        return
    fi
    local detected="unknown"
    local session_type="${XDG_SESSION_TYPE:-}"
    case "${session_type,,}" in
        wayland)
            detected="wayland"
            ;;
        x11|xorg*)
            detected="x11"
            ;;
    esac
    if [[ "$detected" == "unknown" && -n "${WAYLAND_DISPLAY:-}" ]]; then
        detected="wayland"
    fi
    if [[ "$detected" == "unknown" && -n "${DISPLAY:-}" ]]; then
        detected="x11"
    fi
    if [[ "$detected" == "unknown" && -n "${XDG_SESSION_ID:-}" && -n "${XDG_RUNTIME_DIR:-}" ]]; then
        if command -v loginctl >/dev/null 2>&1; then
            local loginctl_type
            loginctl_type="$(loginctl show-session "$XDG_SESSION_ID" -p Type 2>/dev/null | cut -d= -f2)"
            case "${loginctl_type,,}" in
                wayland)
                    detected="wayland"
                    ;;
                x11|xorg*)
                    detected="x11"
                    ;;
            esac
        fi
    fi
    DISPLAY_STACK_DETECTED="$detected"
    printf '%s' "$DISPLAY_STACK_DETECTED"
}

expand_path_template() {
    local template="$1"
    if [[ -z "$template" ]]; then
        return
    fi
    # Allow ${VAR:-default} style expressions from the manifest.
    local expanded
    expanded="$(eval "echo \"$template\"")"
    printf '%s' "$expanded"
}

maybe_create_directory() {
    local target="$1"
    if [[ -d "$target" ]]; then
        return
    fi
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would create directory '$target'."
        return
    fi
    mkdir -p "$target"
}

canonicalize_path() {
    local target="$1"
    if [[ -z "$target" ]]; then
        return
    fi
    if [[ -d "$target" ]]; then
        (cd "$target" >/dev/null 2>&1 && pwd)
    else
        printf '%s' "$target"
    fi
}

expand_user_path() {
    local raw="${1:-}"
    python3 - "$raw" <<'PY'
import os
import sys

raw_value = sys.argv[1]
expanded = os.path.expanduser(os.path.expandvars(raw_value))
print(expanded)
PY
}

prompt_for_manual_plugin_dir() {
    local candidate
    while true; do
        read -r -p "Enter the path to your EDMarketConnector plugins directory: " candidate
        candidate="$(expand_user_path "$candidate")"
        if [[ -z "$candidate" ]]; then
            echo "❌ Path cannot be empty."
            continue
        fi
        if [[ -d "$candidate" ]]; then
            PLUGIN_DIR="$(canonicalize_path "$candidate")"
            echo "✅ Using plugin directory: $PLUGIN_DIR"
            return
        fi
        echo "⚠️  Directory '$candidate' does not exist."
        if prompt_yes_no "Create this directory?"; then
            maybe_create_directory "$candidate"
            PLUGIN_DIR="$(canonicalize_path "$candidate")"
            echo "✅ Created and using plugin directory: $PLUGIN_DIR"
            return
        fi
        echo "Please provide a valid directory."
    done
}

download_with_tool() {
    local url="$1"
    local dest="$2"
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would download '$url' into '$dest'."
        return 0
    fi
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$dest"
        return $?
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -qO "$dest" "$url"
        return $?
    fi
    echo "❌ Neither curl nor wget is available to download '$url'. Install one of them first." >&2
    return 1
}

ensure_font_list_entry() {
    local font_file="$1"
    local preferred_file="$2"
    if [[ ! -f "$preferred_file" ]]; then
        echo "ℹ️  preferred_fonts.txt not found; the overlay will still detect ${font_file} automatically."
        return
    fi
    if grep -iq "^${font_file}$" "$preferred_file"; then
        echo "ℹ️  ${font_file} already listed in preferred_fonts.txt."
        return
    fi
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would append '${font_file}' to '$preferred_file'."
        return
    fi
    echo "${font_file}" >> "$preferred_file"
    echo "✅ Added ${font_file} to preferred_fonts.txt."
}

install_eurocaps_font() {
    local fonts_dir="$1"
    local font_path="${fonts_dir}/${EUROCAPS_FONT_NAME}"
    local preferred_list="${fonts_dir}/preferred_fonts.txt"
    maybe_create_directory "$fonts_dir"
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would download ${EUROCAPS_FONT_NAME} to '$font_path'."
        ensure_font_list_entry "${EUROCAPS_FONT_NAME}" "$preferred_list"
        return 0
    fi
    local tmp_file
    tmp_file="$(mktemp)" || {
        echo "❌ Failed to allocate temporary file for the Eurocaps font." >&2
        return 1
    }
    echo "⬇️  Downloading ${EUROCAPS_FONT_NAME}..."
    if ! download_with_tool "$EUROCAPS_FONT_URL" "$tmp_file"; then
        echo "❌ Unable to download the Eurocaps font." >&2
        rm -f "$tmp_file"
        return 1
    fi
    if [[ ! -s "$tmp_file" ]]; then
        echo "❌ Downloaded Eurocaps font appears to be empty. Aborting." >&2
        rm -f "$tmp_file"
        return 1
    fi
    if command -v install >/dev/null 2>&1; then
        install -m 644 "$tmp_file" "$font_path"
    else
        cp "$tmp_file" "$font_path"
        chmod 644 "$font_path" >/dev/null 2>&1 || true
    fi
    rm -f "$tmp_file"
    echo "✅ Installed ${EUROCAPS_FONT_NAME} to '$font_path'."
    ensure_font_list_entry "${EUROCAPS_FONT_NAME}" "$preferred_list"
    return 0
}

maybe_install_eurocaps() {
    local plugin_home="$1"
    local fonts_dir="${plugin_home}/overlay-client/fonts"
    local font_path="${fonts_dir}/${EUROCAPS_FONT_NAME}"
    if [[ ! -d "$fonts_dir" ]]; then
        echo "ℹ️  Font directory '$fonts_dir' not found; skipping Eurocaps font installation."
        return
    fi
    if [[ -f "$font_path" ]]; then
        echo "ℹ️  ${EUROCAPS_FONT_NAME} already exists at '$font_path'; skipping download."
        return
    fi
    echo "ℹ️  The Eurocaps cockpit font provides the authentic Elite Dangerous HUD look."
    if ! prompt_yes_no "Download and install ${EUROCAPS_FONT_NAME} now?"; then
        echo "ℹ️  Skipping Eurocaps font download."
        return
    fi
    if ! prompt_yes_no "Confirm you already have a license to use the Eurocaps font (e.g., via your Elite Dangerous purchase). Proceed?"; then
        echo "ℹ️  Eurocaps installation cancelled because the license confirmation was declined."
        return
    fi
    install_eurocaps_font "$fonts_dir"
}

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
    if [[ "$ASSUME_YES" == true ]]; then
        echo "${prompt} [y/N]: y (auto-approved)"
        return 0
    fi
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
    load_plugin_path_templates
    local candidate
    if [[ -n "$PLUGIN_DIR_OVERRIDE" ]]; then
        candidate="$(expand_user_path "$PLUGIN_DIR_OVERRIDE")"
        if [[ -z "$candidate" ]]; then
            echo "❌ Provided plugin directory path is empty." >&2
            exit 1
        fi
        if [[ -d "$candidate" ]]; then
            PLUGIN_DIR="$(canonicalize_path "$candidate")"
            echo "✅ Using plugin directory (override): $PLUGIN_DIR"
            return
        fi
        echo "⚠️  Override directory '$candidate' does not exist."
        if prompt_yes_no "Create this directory?"; then
            maybe_create_directory "$candidate"
            PLUGIN_DIR="$(canonicalize_path "$candidate")"
            echo "✅ Using plugin directory: $PLUGIN_DIR"
            return
        fi
        echo "❌ Installation requires a valid plugin directory." >&2
        exit 1
    fi

    local -a standard_candidates=()
    local -a flatpak_candidates=()
    declare -A standard_seen=()
    declare -A flatpak_seen=()
    local template expanded
    for template in "${MATRIX_STANDARD_PATHS[@]}"; do
        expanded="$(expand_path_template "$template")"
        if [[ -n "$expanded" && -z "${standard_seen[$expanded]:-}" ]]; then
            standard_candidates+=("$expanded")
            standard_seen["$expanded"]=1
        fi
    done
    for template in "${MATRIX_FLATPAK_PATHS[@]}"; do
        expanded="$(expand_path_template "$template")"
        if [[ -n "$expanded" && -z "${flatpak_seen[$expanded]:-}" ]]; then
            flatpak_candidates+=("$expanded")
            flatpak_seen["$expanded"]=1
        fi
    done

    local -a combined_candidates=()
    declare -A combined_seen=()
    for candidate in "${standard_candidates[@]}" "${flatpak_candidates[@]}"; do
        if [[ -n "$candidate" && -z "${combined_seen[$candidate]:-}" ]]; then
            combined_candidates+=("$candidate")
            combined_seen["$candidate"]=1
        fi
    done

    local -a existing_standard=()
    local -a existing_flatpak=()
    for candidate in "${standard_candidates[@]}"; do
        if [[ -d "$candidate" ]]; then
            existing_standard+=("$candidate")
        fi
    done
    for candidate in "${flatpak_candidates[@]}"; do
        if [[ -d "$candidate" ]]; then
            existing_flatpak+=("$candidate")
        fi
    done

    if (( ${#existing_standard[@]} > 0 && ${#existing_flatpak[@]} > 0 )); then
        if [[ "$ASSUME_YES" == true ]]; then
            local default_target="${existing_standard[0]}"
            local default_label="base"
            if [[ -z "$default_target" ]]; then
                default_target="${existing_flatpak[0]}"
                default_label="Flatpak"
            fi
            echo "ℹ️  Detected both base and Flatpak EDMC installations; defaulting to the ${default_label} plugins directory '$default_target' due to --assume-yes."
            PLUGIN_DIR="$(canonicalize_path "$default_target")"
            echo "✅ Using plugin directory: $PLUGIN_DIR"
            return
        fi
        echo "✅ Detected both a base EDMC install and a Flatpak EDMC install."
        echo "Select which installation should receive Modern Overlay:"
        local -a option_paths=()
        local -a option_labels=()
        local idx=1
        for candidate in "${existing_standard[@]}"; do
            option_paths+=("$candidate")
            option_labels+=("Base install")
            printf ' %d) Base install: %s\n' "$idx" "$candidate"
            ((idx++))
        done
        for candidate in "${existing_flatpak[@]}"; do
            option_paths+=("$candidate")
            option_labels+=("Flatpak install")
            printf ' %d) Flatpak install: %s\n' "$idx" "$candidate"
            ((idx++))
        done
        echo " C) Enter a different directory"
        local choice
        while true; do
            read -r -p "Choose a target [1-$((idx-1)) or C]: " choice
            choice="${choice,,}"
            if [[ "$choice" == "c" || "$choice" == "custom" ]]; then
                prompt_for_manual_plugin_dir
                return
            fi
            if [[ "$choice" =~ ^[0-9]+$ ]]; then
                local number=$((10#$choice))
                if (( number >= 1 && number < idx )); then
                    local selected="${option_paths[number-1]}"
                    local label="${option_labels[number-1]}"
                    PLUGIN_DIR="$(canonicalize_path "$selected")"
                    echo "✅ Using ${label} directory: $PLUGIN_DIR"
                    return
                fi
            fi
            echo "Unrecognised selection '$choice'."
        done
    fi

    for candidate in "${combined_candidates[@]}"; do
        if [[ -d "$candidate" ]]; then
            echo "✅ Detected EDMarketConnector plugins directory at '$candidate'."
            if prompt_yes_no "Use this directory?"; then
                PLUGIN_DIR="$(canonicalize_path "$candidate")"
                echo "✅ Using plugin directory: $PLUGIN_DIR"
                return
            fi
        fi
    done

    if ((${#combined_candidates[@]} > 0)); then
        local suggested="${combined_candidates[0]}"
        if [[ -n "$suggested" ]]; then
            echo "⚠️  Default plugin directory not found at '$suggested'."
            if prompt_yes_no "Create and use this directory?"; then
                maybe_create_directory "$suggested"
                PLUGIN_DIR="$(canonicalize_path "$suggested")"
                echo "✅ Using plugin directory: $PLUGIN_DIR"
                return
            fi
        fi
    fi

    echo "Unable to automatically locate the EDMarketConnector plugins directory."
    if ((${#combined_candidates[@]} > 0)); then
        echo "Suggested locations to check:"
        for candidate in "${combined_candidates[@]}"; do
            echo "   - $candidate"
        done
    fi

    prompt_for_manual_plugin_dir
}

ensure_edmc_not_running() {
    if command -v pgrep >/dev/null 2>&1 && pgrep -f "EDMarketConnector" >/dev/null 2>&1; then
        echo "⚠️  EDMarketConnector appears to be running."
        if [[ "$ASSUME_YES" == true ]]; then
            echo "❌ Cannot continue in non-interactive mode while EDMarketConnector is running." >&2
            exit 1
        fi
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
        if [[ "$ASSUME_YES" == true ]]; then
            echo "ℹ️  Continuing without automatic EDMarketConnector detection due to --assume-yes."
            return
        fi
        if ! prompt_yes_no "Continue with installation?"; then
            echo "❌ Installation aborted by user." >&2
            exit 1
        fi
    fi
}

disable_conflicting_plugins() {
    if [[ -z "${PLUGIN_DIR:-}" ]]; then
        echo "❌ Plugin directory is not set. Run detect_plugins_dir first." >&2
        exit 1
    fi
    if [[ ! -d "$PLUGIN_DIR" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            echo "📝 [dry-run] Plugin directory '$PLUGIN_DIR' does not exist yet; skipping legacy plugin scan."
            return
        fi
        mkdir -p "$PLUGIN_DIR"
    fi
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
            if [[ "$DRY_RUN" == true ]]; then
                echo "📝 [dry-run] Would rename '$(basename "$path")' to '$(basename "$new_name")'."
            else
                mv "$path" "$new_name"
                echo "   - Disabled $(basename "$path")."
            fi
        done
    else
        echo "❌ Cannot proceed while legacy overlay is enabled. Aborting." >&2
        exit 1
    fi
}

ensure_system_packages() {
    ensure_distro_profile
    local session_stack
    session_stack="$(detect_display_stack)"
    local packages=("${PROFILE_PACKAGES_CORE[@]}" "${PROFILE_PACKAGES_QT[@]}")
    local fallback_notice="python3 python3-venv python3-pip rsync libxcb-cursor0 libxkbcommon-x11-0"
    if [[ "$session_stack" == "wayland" && ${#PROFILE_PACKAGES_WAYLAND[@]} > 0 ]]; then
        packages+=("${PROFILE_PACKAGES_WAYLAND[@]}")
        fallback_notice+=" wmctrl x11-utils"
    elif [[ "$session_stack" == "wayland" ]]; then
        fallback_notice+=" wmctrl x11-utils"
    fi
    if ((${#packages[@]} == 0)); then
        echo "⚠️  Automatic dependency installation is disabled for profile '$PROFILE_LABEL'."
        echo "    Ensure these packages (or their equivalents) are installed manually: ${fallback_notice}"
        return
    fi

    if [[ "$session_stack" == "wayland" && ${#PROFILE_PACKAGES_WAYLAND[@]} > 0 ]]; then
        echo "ℹ️  Wayland session detected; including helper packages with the core dependencies."
    elif [[ "$session_stack" == "x11" && ${#PROFILE_PACKAGES_WAYLAND[@]} > 0 ]]; then
        echo "ℹ️  X11 session detected; skipping Wayland helper packages."
    elif [[ "$session_stack" == "unknown" && ${#PROFILE_PACKAGES_WAYLAND[@]} > 0 ]]; then
        echo "ℹ️  Session type could not be determined automatically; Wayland helper packages will be skipped."
    fi

    echo "📦 Modern Overlay requires the following packages on '$PROFILE_LABEL':"
    printf '    %s\n' "${packages[@]}"

    classify_package_statuses "${packages[@]}"

    if (( ! PACKAGE_STATUS_CHECK_SUPPORTED )); then
        echo "ℹ️  Detailed package status checks are unavailable for this package manager; requesting installation for all listed packages."
    fi

    if ((${#PACKAGES_ALREADY_OK[@]} > 0)); then
        echo "   ✅ Already satisfied:"
        local pkg
        for pkg in "${PACKAGES_ALREADY_OK[@]}"; do
            printf '      - %s (%s)\n' "$pkg" "${PACKAGE_STATUS_DETAILS[$pkg]}"
        done
    fi
    if ((${#PACKAGES_TO_INSTALL[@]} > 0)); then
        echo "   📥 Needs installation:"
        for pkg in "${PACKAGES_TO_INSTALL[@]}"; do
            printf '      - %s (%s)\n' "$pkg" "${PACKAGE_STATUS_DETAILS[$pkg]}"
        done
    fi
    if ((${#PACKAGES_TO_UPGRADE[@]} > 0)); then
        echo "   ⬆️  Needs upgrade:"
        for pkg in "${PACKAGES_TO_UPGRADE[@]}"; do
            printf '      - %s (%s)\n' "$pkg" "${PACKAGE_STATUS_DETAILS[$pkg]}"
        done
    fi

    local -a action_packages=("${PACKAGES_TO_INSTALL[@]}" "${PACKAGES_TO_UPGRADE[@]}")
    if ((${#action_packages[@]} == 0)); then
        echo "✅ All required packages are already present for '$PROFILE_LABEL'."
        return
    fi

    local prompt_message="Install / upgrade ${#action_packages[@]} package(s) now?"
    if ! prompt_yes_no "$prompt_message"; then
        echo "❌ Installation cannot continue without required system packages." >&2
        exit 1
    fi

    require_command sudo "sudo"
    run_package_install "core dependencies" "${action_packages[@]}"
}

create_venv_and_install() {
    local target="$1"
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would ensure Python virtual environment at '$target/overlay-client/.venv' and install overlay-client requirements."
        return
    fi
    if [[ ! -d "$target" ]]; then
        echo "❌ Target directory '$target' not found while preparing virtual environment." >&2
        exit 1
    fi
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
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would copy '$(basename "$src")' into '$plugin_root' and set up overlay-client/.venv."
        return
    fi
    cp -a "$src" "$plugin_root"
    local target="${plugin_root}/$(basename "$src")"
    create_venv_and_install "$target"
}

rsync_update_plugin() {
    local src="$1"
    local dest="$2"
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would update existing installation in '$dest' using rsync while preserving overlay-client/.venv."
        return
    fi
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
        if [[ "$DRY_RUN" == true ]]; then
            echo "📝 [dry-run] Would create Python virtual environment in '$dest/overlay-client/.venv'."
            return
        fi
        create_venv_and_install "$dest"
    fi
}

final_notes() {
    cat <<'EOF'

✅ Installation complete.
ℹ️  Re-run install_linux.sh if you later decide to install (or re-install) the optional Eurocaps font.

EOF
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 Dry-run mode was enabled; no files or packages were modified."
    fi
}

main() {
    parse_args "$@"
    find_release_root
    require_command python3 "python3"
    if [[ ! -f "$MATRIX_FILE" ]]; then
        echo "❌ Matrix manifest '$MATRIX_FILE' is missing. Re-download the release archive." >&2
        exit 1
    fi
    detect_plugins_dir
    ensure_edmc_not_running
    ensure_system_packages
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

    maybe_install_eurocaps "$dest_dir"
    final_notes
    if [[ "$DRY_RUN" != true && "$ASSUME_YES" != true && -t 0 ]]; then
        read -r -p $'Install finished, hit Enter to continue...'
    fi
}

main "$@"
