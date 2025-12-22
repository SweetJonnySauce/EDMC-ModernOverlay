#!/usr/bin/env bash

# install_linux.sh - helper to deploy EDMC Modern Overlay on Linux.

set -euo pipefail
IFS=$'\n\t'

readonly SCRIPT_PATH="${BASH_SOURCE[0]}"
readonly SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
readonly MATRIX_FILE="${SCRIPT_DIR}/install_matrix.json"
readonly EUROCAPS_FONT_URL="https://raw.githubusercontent.com/inorton/EDMCOverlay/master/EDMCOverlay/EDMCOverlay/EUROCAPS.TTF"
readonly EUROCAPS_FONT_NAME="Eurocaps.ttf"
readonly MODERN_PLUGIN_DIR_NAME="EDMCModernOverlay"
readonly LEGACY_PLUGIN_DIR_NAME="EDMC-ModernOverlay"
readonly CHECKSUM_MANIFEST_BASENAME="checksums.txt"
COMPOSITOR_OVERRIDE="auto"

ASSUME_YES=false
DRY_RUN=false
PLUGIN_DIR_OVERRIDE=""
LOG_ENABLED=false
LOG_FILE=""
CHECKSUM_MANIFEST_PATH=""
CHECKSUM_MANIFEST_EFFECTIVE=""
CHECKSUM_MANIFEST_TEMP=""
PLUGIN_DIR_KIND=""

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
declare -a PROFILE_PACKAGES_FLATPAK=()
PKG_UPDATE_COMPLETED=0
PACKAGE_MANAGER_KIND=""
PACKAGE_STATUS_CHECK_SUPPORTED=0
DISPLAY_STACK_DETECTED=""
declare -a PACKAGES_TO_INSTALL=()
declare -a PACKAGES_TO_UPGRADE=()
declare -a PACKAGES_ALREADY_OK=()
declare -A PACKAGE_STATUS_DETAILS=()
COMPOSITOR_SELECTED=0
COMPOSITOR_ID=""
COMPOSITOR_LABEL=""
COMPOSITOR_MATCH_JSON=""
COMPOSITOR_ENV_OVERRIDES_JSON=""
COMPOSITOR_PROVENANCE=""
COMPOSITOR_REQUIRES_FORCE_XWAYLAND=0
COMPOSITOR_SESSION=""
COMPOSITOR_DESKTOPS=""
declare -a COMPOSITOR_NOTES=()

print_usage() {
    cat <<'EOF'
Usage: install_linux.sh [options]

Options:
  -y, --yes, --assume-yes   Automatically answer "yes" to prompts.
      --dry-run             Show the actions that would be taken without making changes.
      --profile <id>        Force a distro profile from scripts/install_matrix.json (e.g. debian, fedora).
      --compositor <id|none|auto>
                             Force compositor profile (default: auto). Use 'none' to skip compositor overrides.
      --log[=<path>]        Write verbose installer output to a log file (default path if omitted).
      --log-file <path>     Alternate way to specify the log file path.
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
            --compositor)
                shift || { echo "❌ --compositor requires an argument." >&2; exit 1; }
                COMPOSITOR_OVERRIDE="${1,,}"
                ;;
            --compositor=*)
                COMPOSITOR_OVERRIDE="${1#*=}"
                COMPOSITOR_OVERRIDE="${COMPOSITOR_OVERRIDE,,}"
                ;;
            --log)
                LOG_ENABLED=true
                if [[ $# -gt 1 ]]; then
                    local maybe_log_path="${2:-}"
                    if [[ -n "$maybe_log_path" && "${maybe_log_path:0:1}" != "-" ]]; then
                        LOG_FILE="$maybe_log_path"
                        shift
                    fi
                fi
                ;;
            --log=*)
                LOG_ENABLED=true
                LOG_FILE="${1#*=}"
                ;;
            --log-file)
                shift || { echo "❌ --log-file requires an argument." >&2; exit 1; }
                LOG_ENABLED=true
                LOG_FILE="$1"
                ;;
            --log-file=*)
                LOG_ENABLED=true
                LOG_FILE="${1#*=}"
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

format_list_or_none() {
    if (($# == 0)); then
        printf 'none'
        return
    fi
    local IFS=' '
    printf '%s' "$*"
}

print_breaking_change_warning() {
    cat <<'EOF'
⚠️  Breaking upgrade notice
    Modern Overlay now installs under the 'EDMCModernOverlay' directory. Any existing
    'EDMC-ModernOverlay' folder will be renamed to 'EDMC-ModernOverlay.disabled',
    'EDMC-ModernOverlay.1.disabled', etc., before the new version is copied. Settings
    are not migrated automatically. Re-enable the previous plugin manually if needed.
EOF
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
    emit_array("PROFILE_PACKAGES_FLATPAK", packages.get("flatpak") or [])


def emit_compositor(entry):
    label = entry.get("label") or entry.get("id") or "Unknown"
    print("COMPOSITOR_FOUND=1")
    print(f"COMPOSITOR_ID={shlex.quote(entry.get('id', 'unknown'))}")
    print(f"COMPOSITOR_LABEL={shlex.quote(label)}")
    match_payload = entry.get("match") or {}
    overrides = entry.get("env_overrides") or {}
    notes = entry.get("notes") or []
    provenance = entry.get("provenance") or ""
    print(f"COMPOSITOR_MATCH_JSON={shlex.quote(json.dumps(match_payload, separators=(',', ':')))}")
    print(f"COMPOSITOR_ENV_OVERRIDES_JSON={shlex.quote(json.dumps(overrides, separators=(',', ':')))}")
    emit_array("COMPOSITOR_NOTES", notes)
    print(f"COMPOSITOR_PROVENANCE={shlex.quote(provenance)}")

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
distros = data.get("distros", [])
compositors = data.get("compositors", [])
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
elif mode == "compositor-list":
    for index, entry in enumerate(compositors, start=1):
        cid = entry.get("id") or f"compositor-{index}"
        label = entry.get("label") or cid
        print(f"{index}|{cid}|{label}")
elif mode == "compositor-by-id":
    target = sys.argv[3].lower()
    for entry in compositors:
        cid = (entry.get("id") or "").lower()
        if cid == target:
            emit_compositor(entry)
            break
elif mode == "compositor-match":
    session = sys.argv[3].lower() if len(sys.argv) > 3 else ""
    desktops_raw = sys.argv[4] if len(sys.argv) > 4 else ""
    desktops = [chunk.lower() for chunk in desktops_raw.split(",") if chunk]
    for entry in compositors:
        match = entry.get("match") or {}
        session_types = normalise(match.get("session_types") or [])
        desktops_cfg = normalise(match.get("desktops") or [])
        if session_types and session not in session_types:
            continue
        if desktops_cfg:
            if not desktops:
                continue
            if not any(val in desktops_cfg for val in desktops):
                continue
        emit_compositor(entry)
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
    PROFILE_PACKAGES_FLATPAK=()
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
            if ! "${PKG_UPDATE_CMD[@]}"; then
                local update_status=$?
                handle_dependency_install_failure "refresh the package index" "$update_status" "${packages[@]}"
            fi
        fi
        PKG_UPDATE_COMPLETED=1
    fi
    echo "ℹ️  Installing ${label} via ${PKG_INSTALL_CMD[1]:-package manager}..."
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] $(format_command "${PKG_INSTALL_CMD[@]}" "${packages[@]}")"
        log_verbose "[dry-run] Would execute: $(format_command "${PKG_INSTALL_CMD[@]}" "${packages[@]}") for ${label}"
    else
        log_verbose "Executing command: $(format_command "${PKG_INSTALL_CMD[@]}" "${packages[@]}") for ${label}"
        if ! "${PKG_INSTALL_CMD[@]}" "${packages[@]}"; then
            local install_status=$?
            handle_dependency_install_failure "install ${label}" "$install_status" "${packages[@]}"
        fi
        log_verbose "Package installation command completed for ${label}"
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
        log_verbose "Package manager kind already determined: ${PACKAGE_MANAGER_KIND}"
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
    log_verbose "Package manager binary '${binary:-unknown}' resolved to kind '${PACKAGE_MANAGER_KIND:-unknown}'"
    printf '%s' "$PACKAGE_MANAGER_KIND"
}

classify_packages_for_apt() {
    local pkg status_line status installed_version candidate policy_output policy_status
    local package_list
    package_list="$(format_list_or_none "$@")"
    log_verbose "Running apt package classification for: ${package_list}"
    for pkg in "$@"; do
        if ! status_line="$(dpkg-query -W -f='${db:Status-Abbrev}\t${Version}\n' "$pkg" 2>/dev/null)"; then
            PACKAGES_TO_INSTALL+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="not installed"
            log_verbose "dpkg-query did not find '$pkg'; marking for installation."
            continue
        fi
        IFS=$'\t' read -r status installed_version <<<"$status_line"
        if [[ "${status}" != ii* || -z "$installed_version" ]]; then
            PACKAGES_TO_INSTALL+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="not installed"
            log_verbose "Package '$pkg' reported status '${status:-unknown}' (version='${installed_version:-n/a}') - scheduling install."
            continue
        fi
        policy_status=0
        policy_output="$(apt-cache policy "$pkg" 2>/dev/null)" || policy_status=$?
        if (( policy_status != 0 )); then
            echo "⚠️  Unable to query candidate version for '$pkg' (apt-cache exit ${policy_status}); requesting installation."
            PACKAGES_TO_INSTALL+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="status check failed (apt-cache exit ${policy_status})"
            log_verbose "apt-cache policy failed for '$pkg' (exit ${policy_status})."
            continue
        fi
        candidate="$(awk '/Candidate:/ {print $2; exit}' <<<"$policy_output")"
        if [[ -z "$candidate" || "$candidate" == "(none)" ]]; then
            candidate="$installed_version"
        fi
        if [[ -n "$candidate" && -n "$installed_version" ]] && dpkg --compare-versions "$candidate" gt "$installed_version"; then
            PACKAGES_TO_UPGRADE+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="installed ${installed_version} → candidate ${candidate}"
            log_verbose "Package '$pkg' upgrade required (${installed_version} → ${candidate})."
        else
            PACKAGES_ALREADY_OK+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="installed ${installed_version}"
            log_verbose "Package '$pkg' already satisfied (version ${installed_version})."
        fi
    done
}

classify_packages_for_pacman() {
    local pkg
    local package_list
    package_list="$(format_list_or_none "$@")"
    log_verbose "Running pacman package classification for: ${package_list}"
    for pkg in "$@"; do
        if pacman -Qq "$pkg" >/dev/null 2>&1; then
            PACKAGES_ALREADY_OK+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="installed"
            log_verbose "Package '$pkg' already installed (pacman -Q)."
        else
            local rc=$?
            PACKAGES_TO_INSTALL+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="not installed (pacman -Q exit ${rc})"
            log_verbose "Package '$pkg' not installed (pacman -Q exit ${rc}); scheduling install."
        fi
    done
}

classify_packages_for_dnf() {
    local pkg installed_evr candidate_evr rc
    local package_list
    package_list="$(format_list_or_none "$@")"
    log_verbose "Running dnf package classification for: ${package_list}"

    local rpm_available=0
    local repoquery_available=0
    local vercmp_available=0

    if command -v rpm >/dev/null 2>&1; then
        rpm_available=1
    fi
    if command -v dnf >/dev/null 2>&1 && dnf repoquery --help >/dev/null 2>&1; then
        repoquery_available=1
    else
        log_verbose "dnf repoquery not available; candidate version checks will be skipped."
    fi
    if command -v rpmdev-vercmp >/dev/null 2>&1; then
        vercmp_available=1
    else
        log_verbose "rpmdev-vercmp not available; upgrade comparisons will be skipped."
    fi

    for pkg in "$@"; do
        installed_evr=""
        if (( rpm_available )); then
            if ! installed_evr="$(rpm -q --qf '%{EVR}' "$pkg" 2>/dev/null)"; then
                rc=$?
                PACKAGES_TO_INSTALL+=("$pkg")
                PACKAGE_STATUS_DETAILS["$pkg"]="not installed (rpm -q exit ${rc})"
                log_verbose "Package '$pkg' not installed (rpm -q exit ${rc}); scheduling install."
                continue
            fi
        else
            if ! dnf list installed "$pkg" >/dev/null 2>&1; then
                rc=$?
                PACKAGES_TO_INSTALL+=("$pkg")
                PACKAGE_STATUS_DETAILS["$pkg"]="not installed (dnf list installed exit ${rc})"
                log_verbose "Package '$pkg' not installed (dnf list installed exit ${rc}); scheduling install."
                continue
            fi
        fi

        candidate_evr=""
        if (( repoquery_available )); then
            if candidate_evr="$(dnf repoquery --latest-limit 1 --qf '%{EVR}' "$pkg" 2>/dev/null)"; then
                candidate_evr="$(printf '%s\n' "$candidate_evr" | head -n1)"
            else
                rc=$?
                log_verbose "dnf repoquery failed for '$pkg' (exit ${rc}); skipping candidate version."
                candidate_evr=""
            fi
        fi

        if [[ -n "$candidate_evr" && -n "$installed_evr" && $vercmp_available -eq 1 ]]; then
            rpmdev-vercmp "$installed_evr" "$candidate_evr" >/dev/null 2>&1
            rc=$?
            case "$rc" in
                0)
                    PACKAGES_ALREADY_OK+=("$pkg")
                    PACKAGE_STATUS_DETAILS["$pkg"]="installed ${installed_evr}"
                    log_verbose "Package '$pkg' already satisfied (version ${installed_evr})."
                    ;;
                11)
                    PACKAGES_ALREADY_OK+=("$pkg")
                    PACKAGE_STATUS_DETAILS["$pkg"]="installed ${installed_evr} (newer than repo ${candidate_evr})"
                    log_verbose "Package '$pkg' newer than repo candidate (${installed_evr} > ${candidate_evr})."
                    ;;
                12)
                    PACKAGES_TO_UPGRADE+=("$pkg")
                    PACKAGE_STATUS_DETAILS["$pkg"]="installed ${installed_evr} → candidate ${candidate_evr}"
                    log_verbose "Package '$pkg' upgrade required (${installed_evr} → ${candidate_evr})."
                    ;;
                *)
                    PACKAGES_ALREADY_OK+=("$pkg")
                    PACKAGE_STATUS_DETAILS["$pkg"]="installed ${installed_evr} (version compare failed)"
                    log_verbose "Package '$pkg' version compare failed (rpmdev-vercmp exit ${rc})."
                    ;;
            esac
        else
            local detail
            if [[ -n "$installed_evr" ]]; then
                detail="installed ${installed_evr}"
            else
                detail="installed (version unknown)"
            fi
            if [[ -z "$candidate_evr" ]]; then
                detail+="; candidate check skipped"
            elif (( ! vercmp_available )); then
                detail+="; version compare skipped"
            fi
            PACKAGES_ALREADY_OK+=("$pkg")
            PACKAGE_STATUS_DETAILS["$pkg"]="$detail"
            log_verbose "Package '$pkg' installed; upgrade check skipped."
        fi
    done
}

classify_package_statuses() {
    reset_package_status_tracking
    local manager_kind
    manager_kind="$(detect_package_manager_kind)"
    local package_list
    package_list="$(format_list_or_none "$@")"
    log_verbose "Classifying package statuses via manager '${manager_kind:-unknown}' for packages: ${package_list}"
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
        dnf)
            PACKAGE_STATUS_CHECK_SUPPORTED=1
            classify_packages_for_dnf "$@"
            ;;
        pacman)
            PACKAGE_STATUS_CHECK_SUPPORTED=1
            classify_packages_for_pacman "$@"
            ;;
        *)
            PACKAGE_STATUS_CHECK_SUPPORTED=0
            PACKAGES_TO_INSTALL=("$@")
            for pkg in "$@"; do
                PACKAGE_STATUS_DETAILS["$pkg"]="status check unsupported for manager '${manager_kind}'"
            done
            ;;
    esac
    local install_list upgrade_list ok_list
    install_list="$(format_list_or_none "${PACKAGES_TO_INSTALL[@]}")"
    upgrade_list="$(format_list_or_none "${PACKAGES_TO_UPGRADE[@]}")"
    ok_list="$(format_list_or_none "${PACKAGES_ALREADY_OK[@]}")"
    log_verbose "Package status summary: install=(${install_list}), upgrade=(${upgrade_list}), ok=(${ok_list})"
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

reset_compositor_selection() {
    COMPOSITOR_SELECTED=0
    COMPOSITOR_FOUND=0
    COMPOSITOR_ID=""
    COMPOSITOR_LABEL=""
    COMPOSITOR_MATCH_JSON=""
    COMPOSITOR_ENV_OVERRIDES_JSON=""
    COMPOSITOR_PROVENANCE=""
    COMPOSITOR_REQUIRES_FORCE_XWAYLAND=0
    COMPOSITOR_SESSION=""
    COMPOSITOR_DESKTOPS=""
    COMPOSITOR_NOTES=()
}

parse_requires_force_xwayland() {
    local match_json="$1"
    if [[ -z "$match_json" ]]; then
        COMPOSITOR_REQUIRES_FORCE_XWAYLAND=0
        return
    fi
    local flag
    flag="$(
        MATCH="$match_json" python3 - <<'PY'
import json, os
raw = os.environ.get("MATCH") or ""
try:
    data = json.loads(raw)
    val = data.get("requires_force_xwayland")
    print("1" if val else "0")
except Exception:
    print("0")
PY
    )"
    if [[ "$flag" == "1" ]]; then
        COMPOSITOR_REQUIRES_FORCE_XWAYLAND=1
    else
        COMPOSITOR_REQUIRES_FORCE_XWAYLAND=0
    fi
}

select_compositor_profile() {
    reset_compositor_selection
    if [[ "${COMPOSITOR_OVERRIDE,,}" == "none" ]]; then
        log_verbose "Compositor override set to 'none'; skipping compositor match."
        return
    fi
    local session="${XDG_SESSION_TYPE:-}"
    session="${session,,}"
    COMPOSITOR_SESSION="$session"
    local desktops_raw="${XDG_CURRENT_DESKTOP:-}"
    desktops_raw="${desktops_raw//:/,}"
    desktops_raw="${desktops_raw//;/,}"
    desktops_raw="${desktops_raw// /,}"
    desktops_raw="${desktops_raw,,}"
    COMPOSITOR_DESKTOPS="$desktops_raw"

    local output=""
    if [[ "${COMPOSITOR_OVERRIDE,,}" != "auto" && -n "${COMPOSITOR_OVERRIDE:-}" ]]; then
        output="$(matrix_helper compositor-by-id "${COMPOSITOR_OVERRIDE,,}")"
        if [[ -z "$output" ]]; then
            echo "⚠️  Unknown compositor profile '${COMPOSITOR_OVERRIDE}'. Skipping compositor-specific overrides." >&2
            return
        fi
        COMPOSITOR_SELECTED=1
        COMPOSITOR_SOURCE="manual"
    else
        output="$(matrix_helper compositor-match "$session" "$desktops_raw")"
        if [[ -z "$output" ]]; then
            log_verbose "No compositor match found for session='${session:-unknown}' desktops='${desktops_raw:-unknown}'."
            return
        fi
        COMPOSITOR_SOURCE="auto"
    fi

    eval "$output"
    if [[ "${COMPOSITOR_FOUND:-0}" -ne 1 ]]; then
        COMPOSITOR_SELECTED=0
        return
    fi
    COMPOSITOR_SELECTED=1
    parse_requires_force_xwayland "${COMPOSITOR_MATCH_JSON:-}"
    log_verbose "Compositor detected: id='${COMPOSITOR_ID}' label='${COMPOSITOR_LABEL}' requires_force_xwayland=${COMPOSITOR_REQUIRES_FORCE_XWAYLAND}"
}

summarise_overrides() {
    local overrides_json="$1"
    OVERRIDES="$overrides_json" python3 - <<'PY'
import json, os
raw = os.environ.get("OVERRIDES") or "{}"
try:
    data = json.loads(raw)
except Exception:
    data = {}
if not isinstance(data, dict) or not data:
    print("    (none)")
else:
    for key, value in data.items():
        print(f"    {key}={value}")
PY
}

apply_compositor_overrides() {
    local target_dir="$1"
    if [[ -z "$target_dir" ]]; then
        return
    fi
    local overrides_json="$COMPOSITOR_ENV_OVERRIDES_JSON"
    if [[ -z "$overrides_json" ]]; then
        overrides_json="{}"
    fi
    if [[ "${overrides_json// /}" == "{}" && "${COMPOSITOR_REQUIRES_FORCE_XWAYLAND:-0}" -eq 0 ]]; then
        log_verbose "Compositor overrides empty and no force_xwayland requirement; skipping write."
        return
    fi
    local target_file="${target_dir}/overlay_client/env_overrides.json"
    local target_dirname
    target_dirname="$(dirname "$target_file")"
    if [[ ! -d "$target_dirname" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            echo "📝 [dry-run] Would create directory '$target_dirname' for compositor overrides."
        else
            mkdir -p "$target_dirname"
        fi
    fi
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would write compositor overrides to '$target_file'."
        summarise_overrides "$overrides_json"
        if [[ "$COMPOSITOR_REQUIRES_FORCE_XWAYLAND" -eq 1 ]]; then
            echo "    (would also set EDMC_OVERLAY_FORCE_XWAYLAND=1)"
        fi
        return
    fi
    local result
    result="$(
        TARGET_FILE="$target_file" \
        OVERRIDES="$overrides_json" \
        REQUIRES_FX="$COMPOSITOR_REQUIRES_FORCE_XWAYLAND" \
        COMPOSITOR_ID="$COMPOSITOR_ID" \
        COMPOSITOR_LABEL="$COMPOSITOR_LABEL" \
        COMPOSITOR_SESSION="$COMPOSITOR_SESSION" \
        COMPOSITOR_DESKTOPS="$COMPOSITOR_DESKTOPS" \
        COMPOSITOR_MATCH_JSON="$COMPOSITOR_MATCH_JSON" \
        COMPOSITOR_PROVENANCE="$COMPOSITOR_PROVENANCE" \
        python3 - <<'PY'
import json, os, sys, tempfile
from pathlib import Path

target = os.environ.get("TARGET_FILE")
if not target:
    print("ERR=missing_target")
    sys.exit(1)
path = Path(target)
overrides = json.loads(os.environ.get("OVERRIDES") or "{}")
requires_fx = os.environ.get("REQUIRES_FX") == "1"
if requires_fx:
    overrides.setdefault("EDMC_OVERLAY_FORCE_XWAYLAND", "1")

existing: dict = {}
if path.exists():
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        existing = {}

env_block = existing.get("env") if isinstance(existing, dict) else {}
if not isinstance(env_block, dict):
    env_block = {}
meta = existing.get("provenance") if isinstance(existing, dict) else {}
if not isinstance(meta, dict):
    meta = {}

applied = []
skipped_env = []
for key, value in overrides.items():
    if os.environ.get(key):
        skipped_env.append(key)
        continue
    if key in env_block:
        continue
    env_block[key] = str(value)
    applied.append(key)

if "compositor_id" not in meta:
    meta["compositor_id"] = os.environ.get("COMPOSITOR_ID", "")
if "compositor_label" not in meta:
    meta["compositor_label"] = os.environ.get("COMPOSITOR_LABEL", "")
if "requires_force_xwayland" not in meta:
    meta["requires_force_xwayland"] = requires_fx
if "session" not in meta and os.environ.get("COMPOSITOR_SESSION"):
    meta["session"] = os.environ["COMPOSITOR_SESSION"]
match_desktops = []
match_raw = os.environ.get("COMPOSITOR_MATCH_JSON")
if match_raw:
    try:
        match_data = json.loads(match_raw)
        if isinstance(match_data, dict):
            desktops_val = match_data.get("desktops")
            if isinstance(desktops_val, list):
                match_desktops = [str(token) for token in desktops_val if token]
    except Exception:
        match_desktops = []
desktops = os.environ.get("COMPOSITOR_DESKTOPS")
if "desktops" not in meta:
    if match_desktops:
        meta["desktops"] = match_desktops
    elif desktops:
        meta["desktops"] = [token for token in desktops.split(",") if token]
provenance = os.environ.get("COMPOSITOR_PROVENANCE")
if provenance and "provenance" not in meta:
    meta["provenance"] = provenance

out = {"env": env_block}
if meta:
    out["provenance"] = meta

tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
tmp.replace(path)

print("APPLIED=" + ",".join(applied))
print("SKIPPED_ENV=" + ",".join(skipped_env))
PY
    2>/dev/null | tr -d '\r'
    )"
    local applied="" skipped_env="" err=""
    while IFS='=' read -r key value; do
        case "$key" in
            APPLIED) applied="$value" ;;
            SKIPPED_ENV) skipped_env="$value" ;;
            ERR) err="$value" ;;
        esac
    done <<<"$result"
    if [[ "$err" == "missing_target" ]]; then
        echo "❌ Internal error: missing target file for compositor overrides." >&2
        return
    fi
    if [[ -n "$applied" ]]; then
        echo "✅ Applied compositor overrides to '$target_file': ${applied}"
    else
        echo "ℹ️  No new compositor overrides were written (all already present or skipped)."
    fi
    if [[ -n "$skipped_env" ]]; then
        echo "ℹ️  Skipped overrides already set in environment: ${skipped_env}"
    fi
}

handle_compositor_overrides() {
    local dest_dir="$1"
    if [[ "${COMPOSITOR_SELECTED:-0}" -ne 1 || "${COMPOSITOR_FOUND:-0}" -ne 1 ]]; then
        log_verbose "No compositor overrides to apply."
        return
    fi
    local overrides_json="$COMPOSITOR_ENV_OVERRIDES_JSON"
    if [[ -z "$overrides_json" ]]; then
        overrides_json="{}"
    fi
    local overrides_present
    overrides_present="$(OVERRIDES="$overrides_json" python3 - <<'PY'
import json, os
raw = os.environ.get("OVERRIDES") or "{}"
try:
    data = json.loads(raw)
except Exception:
    data = {}
print("1" if isinstance(data, dict) and bool(data) else "0")
PY
)"
    echo "ℹ️  Detected compositor: ${COMPOSITOR_LABEL:-unknown} (${COMPOSITOR_ID:-unknown})"
    if [[ -n "${COMPOSITOR_PROVENANCE:-}" ]]; then
        echo "    Reason: ${COMPOSITOR_PROVENANCE}"
    fi
    if [[ ${#COMPOSITOR_NOTES[@]} -gt 0 ]]; then
        local note
        for note in "${COMPOSITOR_NOTES[@]}"; do
            echo "    Note: $note"
        done
    fi
    echo "    Recommended overrides:"
    summarise_overrides "$overrides_json"
    if [[ "$COMPOSITOR_REQUIRES_FORCE_XWAYLAND" -eq 1 ]]; then
        echo "    Will also set EDMC_OVERLAY_FORCE_XWAYLAND=1"
    fi
    if [[ "${overrides_present}" != "1" && "${COMPOSITOR_REQUIRES_FORCE_XWAYLAND:-0}" -eq 0 ]]; then
        echo "ℹ️  No compositor overrides to apply."
        return
    fi
    if [[ "$ASSUME_YES" == true ]]; then
        echo "ℹ️  --yes provided; applying compositor overrides without prompting."
        apply_compositor_overrides "$dest_dir"
        return
    fi
    if prompt_yes_no "Apply these compositor-specific overrides now?"; then
        apply_compositor_overrides "$dest_dir"
    else
        echo "ℹ️  Skipped compositor overrides at user request."
    fi
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

log_verbose() {
    if [[ "$LOG_ENABLED" != true || -z "${LOG_FILE:-}" ]]; then
        return
    fi
    local timestamp message
    timestamp="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || printf 'unknown-time')"
    message="$*"
    printf '[%s] %s\n' "$timestamp" "$message" >>"$LOG_FILE" 2>/dev/null || true
}

init_logging() {
    if [[ "$LOG_ENABLED" != true ]]; then
        return
    fi
    local target="$LOG_FILE"
    if [[ -n "$target" ]]; then
        target="$(expand_user_path "$target")"
    fi
    if [[ -z "$target" ]]; then
        local timestamp
        timestamp="$(date +%Y%m%d-%H%M%S)"
        target="${SCRIPT_DIR}/install_linux_${timestamp}.log"
    fi
    local log_dir
    log_dir="$(dirname "$target")"
    if [[ ! -d "$log_dir" ]]; then
        mkdir -p "$log_dir"
    fi
    LOG_FILE="$(canonicalize_path "$target")"
    if command -v tee >/dev/null 2>&1; then
        exec > >(tee -a "$LOG_FILE") 2>&1
    else
        echo "⚠️  'tee' command not found; install output will be written only to $LOG_FILE."
        exec >"$LOG_FILE" 2>&1
    fi
    echo "ℹ️  Logging installation details to $LOG_FILE"
    log_verbose "Verbose logging initialised (pid=$$)"
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
    local fonts_dir="${plugin_home}/overlay_client/fonts"
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
    if ! prompt_yes_no "Confirm you already have a license to use the Eurocaps font. Proceed?"; then
        echo "ℹ️  Eurocaps installation cancelled because the license confirmation was declined."
        return
    fi
    install_eurocaps_font "$fonts_dir"
}

find_release_root() {
    if [[ -d "${SCRIPT_DIR}/${MODERN_PLUGIN_DIR_NAME}" ]]; then
        RELEASE_ROOT="${SCRIPT_DIR}"
    elif [[ -d "${SCRIPT_DIR}/../${MODERN_PLUGIN_DIR_NAME}" ]]; then
        RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    else
        echo "❌ Could not find ${MODERN_PLUGIN_DIR_NAME} directory alongside install script." >&2
        exit 1
    fi
}

locate_checksum_manifest() {
    local candidate="${RELEASE_ROOT}/${CHECKSUM_MANIFEST_BASENAME}"
    local fallback="${RELEASE_ROOT}/${MODERN_PLUGIN_DIR_NAME}/${CHECKSUM_MANIFEST_BASENAME}"
    if [[ -f "$candidate" ]]; then
        CHECKSUM_MANIFEST_PATH="$candidate"
        CHECKSUM_MANIFEST_EFFECTIVE="$candidate"
        log_verbose "Checksum manifest detected at '$CHECKSUM_MANIFEST_PATH'."
        return
    fi
    if [[ -f "$fallback" ]]; then
        CHECKSUM_MANIFEST_PATH="$fallback"
        CHECKSUM_MANIFEST_EFFECTIVE="$fallback"
        log_verbose "Checksum manifest detected at '$CHECKSUM_MANIFEST_PATH' (inside ${MODERN_PLUGIN_DIR_NAME})."
        return
    fi
    CHECKSUM_MANIFEST_PATH=""
    CHECKSUM_MANIFEST_EFFECTIVE=""
    echo "ℹ️  No checksum manifest '${CHECKSUM_MANIFEST_BASENAME}' found alongside installer; skipping integrity verification."
    log_verbose "No checksum manifest '${CHECKSUM_MANIFEST_BASENAME}' found alongside installer; skipping integrity verification."
}

normalize_checksum_manifest_paths() {
    if [[ -z "${CHECKSUM_MANIFEST_PATH:-}" ]]; then
        return
    fi

    CHECKSUM_MANIFEST_EFFECTIVE="$CHECKSUM_MANIFEST_PATH"
    local legacy_prefix="dist/linux/"
    local sample_path
    sample_path="$(awk 'NR==1 {print $2}' "$CHECKSUM_MANIFEST_PATH" 2>/dev/null || true)"

    if [[ "$sample_path" != "${legacy_prefix}"* ]]; then
        return
    fi

    local trimmed_path="${sample_path#${legacy_prefix}}"
    if [[ -e "${RELEASE_ROOT}/${sample_path}" || ! -e "${RELEASE_ROOT}/${trimmed_path%%/*}" ]]; then
        return
    fi

    local tmp_manifest
    tmp_manifest="$(mktemp -t edmcoverlay-checksums.XXXXXX)"
    sed "s#  ${legacy_prefix}#  #g" "$CHECKSUM_MANIFEST_PATH" >"$tmp_manifest"
    CHECKSUM_MANIFEST_EFFECTIVE="$tmp_manifest"
    CHECKSUM_MANIFEST_TEMP="$tmp_manifest"
    log_verbose "Checksum manifest normalized to '$tmp_manifest' due to legacy dist/linux prefix."
}

cleanup_checksum_manifest_temp() {
    if [[ -n "${CHECKSUM_MANIFEST_TEMP:-}" && -f "$CHECKSUM_MANIFEST_TEMP" ]]; then
        rm -f "$CHECKSUM_MANIFEST_TEMP"
    fi
}

verify_checksums() {
    local base_dir="$1"
    local label="${2:-$base_dir}"
    if [[ -z "${CHECKSUM_MANIFEST_PATH:-}" ]]; then
        return
    fi
    normalize_checksum_manifest_paths
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would verify integrity of '${label}' using $(basename "$CHECKSUM_MANIFEST_PATH")."
        return
    fi
    require_command sha256sum "sha256sum (coreutils)"
    local message="ℹ️  Checking file integrity"
    if [[ "$label" == *"installed"* || "$label" == *"updated"* ]]; then
        message="ℹ️  Checking file integrity of installed files"
    fi
    echo "$message"
    local manifest_path="${CHECKSUM_MANIFEST_EFFECTIVE:-$CHECKSUM_MANIFEST_PATH}"
    local -a sha_flags=()
    if [[ "$LOG_ENABLED" != true ]]; then
        sha_flags+=(--quiet)
    fi
    local sha_output
    if sha_output="$(cd "$base_dir" && sha256sum "${sha_flags[@]}" -c "$manifest_path" 2>&1)"; then
        if [[ "$LOG_ENABLED" == true && -n "$sha_output" ]]; then
            printf '%s\n' "$sha_output"
        fi
        echo "✅ Integrity check passed for ${label}."
        return
    fi

    if [[ -n "$sha_output" ]]; then
        printf '%s\n' "$sha_output" >&2
    fi
    echo "❌ Integrity verification failed for ${label}. Re-download the release archive and try again." >&2

    # Ask before exiting so double-clicked installs don't close immediately.
    local answer
    while true; do
        read -r -p "Continue anyway? [y/N]: " answer || answer=""
        case "${answer,,}" in
            y|yes)
                echo "⚠️  Continuing despite failed integrity check."
                return
                ;;
            ""|n|no)
                echo "❌ Installation aborted due to failed integrity check."
                exit 1
                ;;
            *)
                echo "Please answer yes or no."
                ;;
        esac
    done
}

prompt_yes_no() {
    local prompt="${1:-Continue?}"
    if [[ "$ASSUME_YES" == true ]]; then
        echo "${prompt} [Y/n]: y (auto-approved)"
        return 0
    fi
    local answer
    while true; do
        read -r -p "${prompt} [Y/n]: " answer || return 1
        case "${answer}" in
            [Yy][Ee][Ss]|[Yy]|'') return 0 ;;
            [Nn][Oo]|[Nn]) return 1 ;;
            *) echo "Please answer yes or no." ;;
        esac
    done
}

prompt_yes_no_default_no() {
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

handle_dependency_install_failure() {
    local action="$1"
    local exit_code="$2"
    shift 2
    local -a packages=("$@")
    local package_detail
    package_detail="$(format_list_or_none "${packages[@]}")"
    log_verbose "Dependency action '${action}' failed with status ${exit_code} for packages: ${package_detail}"
    echo "⚠️  Unable to ${action}; the package manager exited with status ${exit_code}." >&2
    if ((${#packages[@]} > 0)); then
        echo "    Affected packages:"
        local pkg
        for pkg in "${packages[@]}"; do
            echo "      - $pkg"
        done
    fi
    if prompt_yes_no "Continue without ensuring these dependencies?"; then
        echo "⚠️  Continuing without verifying ${action}. You may need to install the missing packages manually."
    else
        echo "❌ Installation aborted due to unresolved dependencies." >&2
        exit 1
    fi
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

classify_plugin_directory() {
    PLUGIN_DIR_KIND=""
    if [[ -z "${PLUGIN_DIR:-}" ]]; then
        return
    fi
    local canonical_plugin
    canonical_plugin="$(canonicalize_path "$PLUGIN_DIR")"
    load_plugin_path_templates
    local template expanded candidate
    for template in "${MATRIX_FLATPAK_PATHS[@]}"; do
        expanded="$(expand_path_template "$template")"
        if [[ -z "$expanded" ]]; then
            continue
        fi
        candidate="$(canonicalize_path "$expanded")"
        if [[ "$canonical_plugin" == "$candidate" ]]; then
            PLUGIN_DIR_KIND="flatpak"
            return
        fi
    done
    if [[ "$canonical_plugin" == *"/.var/app/io.edcd.EDMarketConnector/"* ]]; then
        PLUGIN_DIR_KIND="flatpak"
        return
    fi
    PLUGIN_DIR_KIND="standard"
}

ensure_edmc_not_running() {
    if command -v pgrep >/dev/null 2>&1 && pgrep -f "EDMarketConnector" >/dev/null 2>&1; then
        echo "⚠️  EDMarketConnector appears to be running."
        log_verbose "EDMarketConnector process detected via pgrep."
        if [[ "$ASSUME_YES" == true ]]; then
            echo "❌ Cannot continue in non-interactive mode while EDMarketConnector is running." >&2
            exit 1
        fi
        if prompt_yes_no "Quit EDMarketConnector and continue installation?"; then
            echo "Please close EDMarketConnector now, then press Enter to continue."
            read -r _
            if pgrep -f "EDMarketConnector" >/dev/null 2>&1; then
                echo "❌ EDMarketConnector is still running. Aborting." >&2
                log_verbose "Installation aborted because EDMC continued running."
                exit 1
            fi
        else
            echo "❌ Installation requires EDMarketConnector to be closed. Aborting." >&2
            log_verbose "User declined to close EDMarketConnector."
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
            log_verbose "User aborted due to unknown EDMC status."
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

normalize_disabled_suffixes() {
    local base_path="$1"
    local label="$2"
    shopt -s nullglob
    local old_variants=( "${base_path}.disabled."* )
    shopt -u nullglob
    if (( ${#old_variants[@]} == 0 )); then
        return
    fi
    if [[ -n "$label" ]]; then
        echo "ℹ️  Normalizing disabled ${label} directories so they end with '.disabled'."
    else
        echo "ℹ️  Normalizing disabled plugin directories so they end with '.disabled'."
    fi
    for old_path in "${old_variants[@]}"; do
        [[ -d "$old_path" ]] || continue
        local suffix="${old_path#${base_path}.disabled.}"
        if [[ -z "$suffix" ]]; then
            continue
        fi
        local target="${base_path}.${suffix}.disabled"
        if [[ -e "$target" ]]; then
            echo "   - Skipping '$(basename "$old_path")'; target '$(basename "$target")' already exists."
            continue
        fi
        if [[ "$DRY_RUN" == true ]]; then
            echo "📝 [dry-run] Would rename '$(basename "$old_path")' to '$(basename "$target")'."
        else
            mv "$old_path" "$target"
            echo "   - Renamed '$(basename "$old_path")' to '$(basename "$target")'."
        fi
    done
}

disable_legacy_modern_overlay() {
    if [[ -z "${PLUGIN_DIR:-}" ]]; then
        echo "❌ Plugin directory is not set. Run detect_plugins_dir first." >&2
        exit 1
    fi
    local legacy_path="${PLUGIN_DIR}/${LEGACY_PLUGIN_DIR_NAME}"
    if [[ ! -d "$legacy_path" ]]; then
        return
    fi
    echo "⚠️  Found existing ${LEGACY_PLUGIN_DIR_NAME} installation."
    echo "    It will be disabled before installing ${MODERN_PLUGIN_DIR_NAME}."
    local suffix=0
    local target
    while :; do
        if (( suffix == 0 )); then
            target="${legacy_path}.disabled"
        else
            target="${legacy_path}.${suffix}.disabled"
        fi
        if [[ ! -e "$target" ]]; then
            break
        fi
        ((++suffix))
    done
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would rename '$(basename "$legacy_path")' to '$(basename "$target")'."
    else
        mv "$legacy_path" "$target"
        echo "   - Legacy plugin renamed to '$(basename "$target")'."
    fi
}

ensure_system_packages() {
    ensure_distro_profile
    local session_stack
    session_stack="$(detect_display_stack)"
    log_verbose "Using distro profile '${PROFILE_LABEL:-unknown}' (id='${PROFILE_ID:-unknown}', source='${PROFILE_SOURCE:-unknown}'). Session stack: ${session_stack:-unknown}"
    local update_cmd install_cmd
    update_cmd="$(format_list_or_none "${PKG_UPDATE_CMD[@]}")"
    install_cmd="$(format_list_or_none "${PKG_INSTALL_CMD[@]}")"
    log_verbose "Package commands: update=(${update_cmd}), install=(${install_cmd})"
    local packages=("${PROFILE_PACKAGES_CORE[@]}" "${PROFILE_PACKAGES_QT[@]}")
    local fallback_notice="python3 python3-venv python3-pip rsync libxcb-cursor0 libxkbcommon-x11-0"
    if [[ "$session_stack" == "wayland" && ${#PROFILE_PACKAGES_WAYLAND[@]} > 0 ]]; then
        packages+=("${PROFILE_PACKAGES_WAYLAND[@]}")
        fallback_notice+=" wmctrl x11-utils"
    elif [[ "$session_stack" == "wayland" ]]; then
        fallback_notice+=" wmctrl x11-utils"
    fi
    if [[ "${PLUGIN_DIR_KIND:-}" == "flatpak" && ${#PROFILE_PACKAGES_FLATPAK[@]} > 0 ]]; then
        packages+=("${PROFILE_PACKAGES_FLATPAK[@]}")
        fallback_notice+=" flatpak-spawn"
    fi
    if ((${#packages[@]} == 0)); then
        echo "⚠️  Automatic dependency installation is disabled for profile '$PROFILE_LABEL'."
        echo "    Ensure these packages (or their equivalents) are installed manually: ${fallback_notice}"
        log_verbose "Automatic dependency installation disabled; fallback packages: ${fallback_notice}"
        return
    fi

    if [[ "$session_stack" == "wayland" && ${#PROFILE_PACKAGES_WAYLAND[@]} > 0 ]]; then
        echo "ℹ️  Wayland session detected; including helper packages with the core dependencies."
        echo "ℹ️  Wayland-specific Python dependencies install inside overlay_client/.venv when detected; no system package is required."
    elif [[ "$session_stack" == "x11" && ${#PROFILE_PACKAGES_WAYLAND[@]} > 0 ]]; then
        echo "ℹ️  X11 session detected; skipping Wayland helper packages."
    elif [[ "$session_stack" == "unknown" && ${#PROFILE_PACKAGES_WAYLAND[@]} > 0 ]]; then
        echo "ℹ️  Session type could not be determined automatically; Wayland helper packages will be skipped."
    fi
    if [[ "${PLUGIN_DIR_KIND:-}" == "flatpak" && ${#PROFILE_PACKAGES_FLATPAK[@]} > 0 ]]; then
        echo "ℹ️  Flatpak EDMC install detected; including Flatpak helper packages."
    fi

    echo "📦 Modern Overlay requires the following packages on '$PROFILE_LABEL':"
    printf '    %s\n' "${packages[@]}"
    local package_list
    package_list="$(format_list_or_none "${packages[@]}")"
    log_verbose "Packages to evaluate: ${package_list}"

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
        log_verbose "All required packages satisfied for profile '${PROFILE_LABEL}'."
        return
    fi

    local prompt_message="Install / upgrade ${#action_packages[@]} package(s) now?"
    if ! prompt_yes_no "$prompt_message"; then
        echo "❌ Installation cannot continue without required system packages." >&2
        local declined_list
        declined_list="$(format_list_or_none "${action_packages[@]}")"
        log_verbose "User declined package installation for: ${declined_list}"
        exit 1
    fi

    require_command sudo "sudo"
    run_package_install "core dependencies" "${action_packages[@]}"
}

create_venv_and_install() {
    local target="$1"
    log_verbose "Ensuring overlay_client virtualenv inside '$target' (dry-run=${DRY_RUN})."
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would ensure Python virtual environment at '$target/overlay_client/.venv' and install overlay_client requirements."
        return
    fi
    if [[ ! -d "$target" ]]; then
        echo "❌ Target directory '$target' not found while preparing virtual environment." >&2
        exit 1
    fi
    pushd "$target" >/dev/null
    if [[ ! -d overlay_client ]]; then
        echo "❌ Missing overlay_client directory in $target. Aborting." >&2
        popd >/dev/null
        exit 1
    fi

    local rebuild_requested=0
    if [[ -d overlay_client/.venv ]]; then
        echo "ℹ️  Existing Python virtual environment detected at overlay_client/.venv."
        if prompt_yes_no_default_no "Rebuild the overlay_client virtual environment?"; then
            rebuild_requested=1
        fi
    fi

    if (( rebuild_requested )); then
        echo "🧹 Removing existing virtual environment before rebuilding..."
        rm -rf overlay_client/.venv
    fi

    if [[ ! -d overlay_client/.venv ]]; then
        echo "🐍 Creating Python virtual environment..."
        python3 -m venv overlay_client/.venv
    fi

    # shellcheck disable=SC1091
    source overlay_client/.venv/bin/activate
    echo "📦 Installing overlay client requirements..."
    pip install --upgrade pip >/dev/null
    pip install -r overlay_client/requirements/base.txt

    local session_stack
    session_stack="$(detect_display_stack)"
    if [[ "$session_stack" == "wayland" ]]; then
        echo "📦 Installing Wayland-specific Python helpers into the virtualenv..."
        pip install -r overlay_client/requirements/wayland.txt
    else
        echo "ℹ️  Skipping Wayland-specific Python helpers (session type: ${session_stack:-unknown})."
    fi
    deactivate

    popd >/dev/null
    log_verbose "overlay_client virtualenv ready at '$target/overlay_client/.venv'."
}

copy_initial_install() {
    local src="$1"
    local plugin_root="$2"
    echo "📁 Copying Modern Overlay into plugins directory..."
    log_verbose "Copying initial install from '$src' to '$plugin_root' (dry-run=${DRY_RUN})."
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would copy '$(basename "$src")' into '$plugin_root' and set up overlay_client/.venv."
        return
    fi
    cp -a "$src" "$plugin_root"
    local target="${plugin_root}/$(basename "$src")"
    verify_checksums "$plugin_root" "installed plugin files"
    create_venv_and_install "$target"
}

rsync_update_plugin() {
    local src="$1"
    local dest="$2"
    log_verbose "Updating existing installation at '$dest' from '$src' (dry-run=${DRY_RUN})."
    if [[ "$DRY_RUN" == true ]]; then
        echo "📝 [dry-run] Would update existing installation in '$dest' using rsync while preserving overlay_client/.venv."
        return
    fi
    if ! command -v rsync >/dev/null 2>&1; then
        echo "❌ rsync is required to update the plugin without overwriting the virtualenv." >&2
        exit 1
    fi

    local excludes=(
        "--exclude" "overlay_client/.venv/"
        "--exclude" "overlay_client/fonts/[Ee][Uu][Rr][Oo][Cc][Aa][Pp][Ss].ttf"
        "--exclude" "overlay_groupings.user.json"
    )

    echo "🔄 Updating existing Modern Overlay installation..."
    rsync -av --delete "${excludes[@]}" "$src"/ "$dest"/
    log_verbose "rsync update completed for '$dest'."
    verify_checksums "$(dirname "$dest")" "updated plugin files"
}

ensure_existing_install() {
    local dest="$1"
    log_verbose "Ensuring existing install at '$dest' has up-to-date dependencies."
    create_venv_and_install "$dest"
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

check_flatpak_permission() {
    if [[ "${PLUGIN_DIR_KIND:-}" != "flatpak" ]]; then
        return
    fi
    pause_flatpak_warning() {
        if [[ "$ASSUME_YES" == true ]]; then
            log_verbose "Assume-yes enabled; skipping Flatpak warning pause."
            return
        fi
        read -r -p "Press Enter to continue (Ctrl+C to abort)... " _
    }
    local app_id="io.edcd.EDMarketConnector"
    if ! command -v flatpak >/dev/null 2>&1; then
        echo "⚠️  Flatpak EDMC install detected but the 'flatpak' CLI is not available; cannot verify host-launch permission."
        echo "    Modern Overlay launches the overlay client via flatpak-spawn --host, which requires D-Bus access to org.freedesktop.Flatpak."
        echo "    Grant it before starting EDMC: flatpak override --user ${app_id} --talk-name=org.freedesktop.Flatpak"
        pause_flatpak_warning
        return
    fi

    local scope_flag=""
    local scope_label="system"
    if flatpak info --user "$app_id" >/dev/null 2>&1; then
        scope_flag="--user"
        scope_label="user"
    elif ! flatpak info "$app_id" >/dev/null 2>&1; then
        echo "⚠️  Flatpak EDMC install not found; skipping Flatpak permission check."
        return
    fi

    local permissions_output=""
    if ! permissions_output="$(flatpak info ${scope_flag:+$scope_flag} --show-permissions "$app_id" 2>/dev/null)"; then
        echo "⚠️  Could not read Flatpak permissions for ${scope_label} ${app_id}; skipping permission check."
        return
    fi

    local session_bus_policy
    session_bus_policy="$(printf '%s\n' "$permissions_output" | awk '/^\[Session Bus Policy\]/{flag=1;next}/^\[/{flag=0}flag')"

    local permission_line=""
    permission_line="$(printf '%s\n' "$session_bus_policy" | grep 'org\.freedesktop\.Flatpak' | head -n1 || true)"
    if [[ -n "$permission_line" ]]; then
        echo "✅ Flatpak permission present (${scope_label} scope): ${permission_line}"
        return
    fi

    local override_line=""
    override_line="$(flatpak override --user --show "$app_id" 2>/dev/null | grep -- '--talk-name=org.freedesktop.Flatpak' | head -n1 || true)"
    if [[ -n "$override_line" ]]; then
        echo "✅ Flatpak user override present: ${override_line}"
        return
    fi

    echo "⚠️  Flatpak EDMC (${scope_label}) is missing host D-Bus access to org.freedesktop.Flatpak."
    echo "    The overlay client is launched outside the sandbox via flatpak-spawn --host and needs this permission."
    local cmd="flatpak override --user ${app_id} --talk-name=org.freedesktop.Flatpak"
    cmd="${cmd//  / }"
    echo "    Grant it before starting EDMC:"
    echo "      ${cmd}"
    pause_flatpak_warning
}

main() {
    trap cleanup_checksum_manifest_temp EXIT
    local -a ORIGINAL_ARGS=("$@")
    parse_args "$@"
    find_release_root
    require_command python3 "python3"
    if ! python3 - <<'PY' 2>/dev/null; then
import sys
sys.exit(0) if sys.version_info >= (3, 10) else sys.exit(1)
PY
        version_raw="$(python3 -V 2>/dev/null || true)"
        echo "❌ Python 3.10+ is required but was not found on PATH (python3). Detected: ${version_raw:-unknown}" >&2
        read -r -p "Continue anyway with the available python3? [y/N] " reply
        if [[ "${reply,,}" != "y" && "${reply,,}" != "yes" ]]; then
            exit 1
        fi
        echo "⚠️  Continuing with python3 despite version check failure."
    fi
    init_logging
    locate_checksum_manifest
    verify_checksums "$RELEASE_ROOT" "release bundle"
    print_breaking_change_warning
    if ((${#ORIGINAL_ARGS[@]} > 0)); then
        log_verbose "Command-line arguments: $(format_list_or_none "${ORIGINAL_ARGS[@]}")"
    else
        log_verbose "Command-line arguments: <none>"
    fi
    log_verbose "Release root resolved to: ${RELEASE_ROOT:-unknown}"
    if [[ ! -f "$MATRIX_FILE" ]]; then
        echo "❌ Matrix manifest '$MATRIX_FILE' is missing. Re-download the release archive." >&2
        exit 1
    fi
    detect_plugins_dir
    classify_plugin_directory
    log_verbose "Plugin directory resolved to: ${PLUGIN_DIR:-unset}"
    ensure_edmc_not_running
    log_verbose "Confirmed EDMarketConnector is not running."
    ensure_system_packages
    check_flatpak_permission
    select_compositor_profile
    disable_conflicting_plugins
    normalize_disabled_suffixes "${PLUGIN_DIR}/${LEGACY_PLUGIN_DIR_NAME}" "${LEGACY_PLUGIN_DIR_NAME}"
    normalize_disabled_suffixes "${PLUGIN_DIR}/${MODERN_PLUGIN_DIR_NAME}" "${MODERN_PLUGIN_DIR_NAME}"
    disable_legacy_modern_overlay

    local src_dir="${RELEASE_ROOT}/${MODERN_PLUGIN_DIR_NAME}"
    if [[ ! -d "$src_dir" ]]; then
        echo "❌ Source directory '$src_dir' not found. Aborting." >&2
        exit 1
    fi

    local dest_dir="${PLUGIN_DIR}/${MODERN_PLUGIN_DIR_NAME}"

    if [[ ! -d "$dest_dir" ]]; then
        copy_initial_install "$src_dir" "$PLUGIN_DIR"
    else
        echo "⚠️  An existing installation was detected at '$dest_dir'."
        echo "    Plugin files will be replaced; you'll be prompted whether to rebuild overlay_client/.venv afterwards."
        if ! prompt_yes_no "Proceed with updating the installation?"; then
            echo "❌ Installation aborted by user to protect the existing virtual environment." >&2
            if [[ -t 0 ]]; then
                read -r -p $'Hit Enter to continue...'
            fi
            exit 1
        fi
        rsync_update_plugin "$src_dir" "$dest_dir"
        ensure_existing_install "$dest_dir"
    fi

    maybe_install_eurocaps "$dest_dir"
    handle_compositor_overrides "$dest_dir"
    final_notes
    if [[ "$DRY_RUN" != true && "$ASSUME_YES" != true && -t 0 ]]; then
        read -r -p $'Install finished, hit Enter to continue...'
    fi
}

if [[ -z "${MODERN_OVERLAY_INSTALLER_IMPORT:-}" ]]; then
    main "$@"
fi
