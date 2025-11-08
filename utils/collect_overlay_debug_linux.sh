#!/usr/bin/env bash

# Collect EDMC Modern Overlay diagnostics for support.

set -u
IFS=$'\n\t'

fail() {
    printf 'collect_overlay_debug.sh: %s\n' "$1" >&2
    exit 1
}

resolve_realpath() {
    local target="$1"
    if command -v realpath >/dev/null 2>&1; then
        realpath "$target"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$target" <<'PY'
import os
import sys
print(os.path.realpath(sys.argv[1]))
PY
        return
    fi
    local dir
    dir="$(cd "$(dirname "$target")" && pwd)" || return 1
    printf '%s/%s\n' "$dir" "$(basename "$target")"
}

validate_plugin_root() {
    local root="$1"
    local missing=0
    local required_dirs=(
        "overlay-client"
        "overlay_plugin"
    )
    local required_files=(
        "edmcoverlay.py"
        "load.py"
    )

    for rel in "${required_dirs[@]}"; do
        if [[ ! -d "${root}/${rel}" ]]; then
            printf 'collect_overlay_debug.sh: expected directory missing: %s\n' "${root}/${rel}" >&2
            missing=1
        fi
    done

    for rel in "${required_files[@]}"; do
        if [[ ! -f "${root}/${rel}" ]]; then
            printf 'collect_overlay_debug.sh: expected file missing: %s\n' "${root}/${rel}" >&2
            missing=1
        fi
    done

    if [[ $missing -ne 0 ]]; then
        return 1
    fi

    return 0
}

plugin_root_is_valid() {
    local root="$1"
    [[ -n "$root" ]] || return 1
    validate_plugin_root "$root" >/dev/null 2>&1
}

confirm_plugin_root() {
    local detected="$1"
    local suggested="${2:-}"
    local candidate=""

    if [[ -n "$detected" ]] && plugin_root_is_valid "$detected"; then
        candidate="$detected"
    fi

    if [[ ! -t 0 ]]; then
        local resolved=""
        if [[ -n "$candidate" ]]; then
            if ! resolved="$(resolve_realpath "$candidate" 2>/dev/null)"; then
                resolved="$candidate"
            fi
            printf 'Detected plugin root: %s (non-interactive, accepting)\n' "$resolved" >&2
            printf '%s\n' "$resolved"
            return 0
        fi
        if [[ -n "$suggested" ]] && plugin_root_is_valid "$suggested"; then
            if ! resolved="$(resolve_realpath "$suggested" 2>/dev/null)"; then
                resolved="$suggested"
            fi
            printf 'Using suggested plugin root: %s (non-interactive)\n' "$resolved" >&2
            printf '%s\n' "$resolved"
            return 0
        fi
        fail "unable to locate a valid EDMC Modern Overlay installation. Run interactively and provide the plugin path."
    fi

    local current="$candidate"
    if [[ -z "$current" ]]; then
        current="$suggested"
    fi

    while true; do
        local is_valid=0
        if [[ -n "$current" ]] && plugin_root_is_valid "$current"; then
            is_valid=1
        fi

        if (( is_valid )); then
            printf 'Detected plugin root: %s\n' "$current" >&2
            printf 'Use this location? [Y/n]: ' >&2
            local response
            if ! read -r response; then
                return 1
            fi
            response="${response:-Y}"
            case "$response" in
                [Yy]*)
                    local resolved
                    if ! resolved="$(resolve_realpath "$current" 2>/dev/null)"; then
                        resolved="$current"
                    fi
                    printf '%s\n' "$resolved"
                    return 0
                    ;;
                [Nn]*)
                    current=""
                    continue
                    ;;
                *)
                    printf 'Please answer yes or no.\n' >&2
                    continue
                    ;;
            esac
        fi

        if [[ -n "$current" ]] && (( ! is_valid )); then
            printf 'The path "%s" does not look like an EDMC Modern Overlay installation.\n' "$current" >&2
        elif [[ -z "$current" ]]; then
            printf 'Unable to detect the plugin location automatically.\n' >&2
        fi

        if [[ -n "$suggested" ]]; then
            printf 'Suggested location: %s\n' "$suggested" >&2
        fi

        if [[ -n "$suggested" ]]; then
            printf 'Enter plugin root path [%s]: ' "$suggested" >&2
        else
            printf 'Enter plugin root path: ' >&2
        fi

        local input
        if ! read -r input; then
            return 1
        fi

        if [[ -z "$input" ]]; then
            if [[ -n "$suggested" ]]; then
                input="$suggested"
            else
                printf 'Path cannot be empty.\n' >&2
                current=""
                continue
            fi
        fi

        local resolved
        if ! resolved="$(resolve_realpath "$input" 2>/dev/null)"; then
            printf 'collect_overlay_debug.sh: unable to resolve path: %s\n' "$input" >&2
            current=""
            continue
        fi

        current="$resolved"
    done
}

LOG_LINES=60
SHOW_LOGS=0

usage() {
    cat <<'EOF'
Usage: collect_overlay_debug.sh [--log-lines N]

Gather environment details, dependency checks, and recent overlay logs.

Options:
  --log-lines N   Number of lines to tail from the newest overlay-client log (default: 60)
  --show-logs     Include overlay-client log tail output
  -h, --help      Show this help message and exit
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --log-lines)
            shift || { echo "Missing value for --log-lines" >&2; exit 1; }
            value="${1:-}"
            if [[ -z "$value" || ! "$value" =~ ^[0-9]+$ ]]; then
                echo "Invalid log line count: ${value:-<empty>}" >&2
                exit 1
            fi
            LOG_LINES="$value"
            ;;
        --show-logs)
            SHOW_LOGS=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift || break
done

SCRIPT_PATH="$(resolve_realpath "${BASH_SOURCE[0]}")" || fail "unable to resolve script path."
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)" || fail "unable to determine script directory."
DETECTED_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)" || fail "unable to determine plugin root."
DEFAULT_PLUGIN_ROOT="${HOME}/.local/share/EDMarketConnector/plugins/EDMC-ModernOverlay"
ROOT_DIR="$(confirm_plugin_root "$DETECTED_ROOT" "$DEFAULT_PLUGIN_ROOT")" || fail "unable to confirm plugin root."
plugin_root_is_valid "$ROOT_DIR" || fail "unable to locate a valid EDMC Modern Overlay installation."
OVERLAY_CLIENT_DIR="${ROOT_DIR}/overlay-client"
SETTINGS_PATH="${ROOT_DIR}/overlay_settings.json"
PORT_PATH="${ROOT_DIR}/port.json"

print_header() {
    printf '\n=== %s ===\n' "$1"
}

print_system_info() {
    print_header "System Information"
    if command -v python3 >/dev/null 2>&1; then
        platform_desc=$(python3 -c 'import platform; print(platform.platform())' 2>/dev/null || echo "unavailable")
    else
        platform_desc="unavailable"
    fi
    printf 'platform: %s\n' "$platform_desc"
    printf 'system: %s\n' "$(uname -s 2>/dev/null || echo unknown)"
    printf 'release: %s\n' "$(uname -r 2>/dev/null || echo unknown)"
    printf 'version: %s\n' "$(uname -v 2>/dev/null || echo unknown)"
    printf 'machine: %s\n' "$(uname -m 2>/dev/null || echo unknown)"
    if command -v python3 >/dev/null 2>&1; then
        printf 'python: %s\n' "$(python3 -V 2>&1)"
    else
        printf 'python: python3 not found\n'
    fi
}

print_environment() {
    print_header "Environment Variables"
    local vars=(
        XDG_SESSION_TYPE
        XDG_CURRENT_DESKTOP
        WAYLAND_DISPLAY
        DISPLAY
        QT_QPA_PLATFORM
        QT_QPA_PLATFORMTHEME
        QT_PLUGIN_PATH
        GDK_BACKEND
        EDMC_OVERLAY_FORCE_XWAYLAND
        EDMC_OVERLAY_SESSION_TYPE
        EDMC_OVERLAY_COMPOSITOR
    )
    for key in "${vars[@]}"; do
        if [[ -v $key ]]; then
            printf '%s=%s\n' "$key" "${!key}"
        else
            printf '%s=<unset>\n' "$key"
        fi
    done
}

print_command_availability() {
    print_header "Command Availability"
    local entries=(
        'wmctrl|-V'
        'xwininfo|-version'
        'xprop|-version'
        'swaymsg|-t get_version'
        'hyprctl|version'
    )

    for entry in "${entries[@]}"; do
        local cmd="${entry%%|*}"
        local args="${entry#*|}"
        if command -v "$cmd" >/dev/null 2>&1; then
            local path
            path="$(command -v "$cmd")"
            printf '%s: %s\n' "$cmd" "$path"
            if [[ -n "$args" ]]; then
                # shellcheck disable=SC2206  # intentional word splitting for args list
                local arg_array=( $args )
                local output
                output=$("$cmd" "${arg_array[@]}" 2>&1)
                local status=$?
                if [[ -n "$output" ]]; then
                    while IFS= read -r line; do
                        printf '  %s\n' "$line"
                    done <<<"$output"
                elif [[ $status -ne 0 ]]; then
                    printf '  note: exit %d with no output\n' "$status"
                fi
            fi
        else
            printf '%s: <not found>\n' "$cmd"
        fi
    done
}

check_required_packages() {
    print_header "Required Packages"
    local packages=(
        libxcb-cursor0
        libxkbcommon-x11-0
    )

    if command -v dpkg-query >/dev/null 2>&1; then
        for pkg in "${packages[@]}"; do
            if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
                printf '%s: installed\n' "$pkg"
            else
                printf '%s: MISSING\n' "$pkg"
            fi
        done
    else
        echo "dpkg-query not available; unable to verify package installation."
    fi
}

abbrev_path() {
    local path="$1"
    if [[ -n "${HOME:-}" && "$path" == "$HOME"* ]]; then
        printf '~%s' "${path#$HOME}"
    else
        printf '%s' "$path"
    fi
}

check_python_modules() {
    print_header "Python Module Checks"
    local modules=(pywayland pydbus)
    local interpreters=()
    local venv_python="${OVERLAY_CLIENT_DIR}/.venv/bin/python"
    if [[ -x "$venv_python" ]]; then
        interpreters+=("$venv_python")
    fi
    if command -v python3 >/dev/null 2>&1; then
        interpreters+=("$(command -v python3)")
    fi
    if ((${#interpreters[@]} == 0)); then
        interpreters+=(python3)
    fi

    for module in "${modules[@]}"; do
        printf '%s:\n' "$module"
        local found=0
        for interpreter in "${interpreters[@]}"; do
            local display
            display=$(abbrev_path "$interpreter")
            if [[ ! -x "$interpreter" ]]; then
                printf '  %s: interpreter not executable\n' "$display"
                continue
            fi
            local output
            output=$("$interpreter" -c "import ${module}" 2>&1)
            local status=$?
            if [[ $status -eq 0 ]]; then
                printf '  %s: available\n' "$display"
                found=1
                break
            else
                local summary="import_failed"
                if [[ -n "$output" ]]; then
                    if grep -q "ModuleNotFoundError" <<<"$output"; then
                        summary="missing module"
                    elif grep -q "ImportError" <<<"$output"; then
                        summary="import error"
                    fi
                fi
                printf '  %s: %s\n' "$display" "$summary"
            fi
        done
        if [[ $found -eq 0 ]]; then
            printf '  (module unavailable in checked interpreters)\n'
        fi
    done
}

check_virtualenv() {
    print_header "Overlay Client Virtualenv"
    local venv_dir="${OVERLAY_CLIENT_DIR}/.venv"
    local venv_python="${venv_dir}/bin/python"
    local venv_pip="${venv_dir}/bin/pip"
    local requirements_file="${OVERLAY_CLIENT_DIR}/requirements.txt"

    if [[ -d "$venv_dir" ]]; then
        printf '.venv: %s\n' "$(abbrev_path "$venv_dir")"
    else
        printf '.venv: <missing>\n'
    fi

    if [[ -x "$venv_python" ]]; then
        printf 'python: %s\n' "$(abbrev_path "$venv_python")"
        local version
        version=$("$venv_python" -V 2>&1)
        printf 'python version: %s\n' "$version"
    else
        printf 'python: <missing>\n'
    fi

    if [[ -x "$venv_pip" ]]; then
        local pip_version
        pip_version=$("$venv_pip" --version 2>&1)
        if [[ -n "${HOME:-}" && "$HOME" != "/" ]]; then
            # shellcheck disable=SC2001
            pip_version="$(printf '%s' "$pip_version" | sed "s#${HOME//\//\\/}#~#g")"
        fi
        printf 'pip: %s\n' "$pip_version"
    else
        printf 'pip: <missing>\n'
    fi

    if [[ -f "$requirements_file" ]]; then
        printf 'requirements.txt: %s\n' "$(abbrev_path "$requirements_file")"
    else
        printf 'requirements.txt: <missing>\n'
    fi

    if [[ -x "$venv_python" && -f "$requirements_file" ]]; then
        local check_output
        if check_output="$("$venv_python" - "$requirements_file" <<'PY'
import sys
from pathlib import Path
try:
    import importlib.metadata as metadata
except ImportError:
    import importlib_metadata as metadata

try:
    from packaging.requirements import Requirement
except Exception:
    Requirement = None

req_path = Path(sys.argv[1])
missing = []
evaluated = 0
lines = req_path.read_text(encoding='utf-8').splitlines()

for raw_line in lines:
    line = raw_line.strip()
    if not line or line.startswith('#'):
        continue
    candidate = line
    if Requirement is not None:
        try:
            req = Requirement(candidate)
        except Exception:
            req = None
        if req is not None:
            if req.marker and not req.marker.evaluate():
                continue
            candidate = req.name
    else:
        candidate = candidate.split('#', 1)[0].strip()
        for sep in ('[', ';', '<', '>', '=', '!', '~', ' ', '\t'):
            idx = candidate.find(sep)
            if idx != -1:
                candidate = candidate[:idx]
                break
    name = candidate.strip()
    if not name:
        continue
    evaluated += 1
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        missing.append(name)

if not evaluated:
    print('no installable requirements listed')
elif missing:
    print('missing packages: ' + ', '.join(sorted(set(missing))))
    sys.exit(1)
else:
    print('requirements satisfied')
PY
)"; then
            if [[ -n "$check_output" ]]; then
                while IFS= read -r line; do
                    printf '  %s\n' "$line"
                done <<<"$check_output"
            else
                printf '  requirements status: ok\n'
            fi
        else
            local status=$?
            if [[ -n "$check_output" ]]; then
                while IFS= read -r line; do
                    printf '  %s\n' "$line"
                done <<<"$check_output"
            fi
            printf '  requirements status: pip check failed (exit %d)\n' "$status"
        fi
    fi
}

gather_overlay_log_candidates() {
    local search_roots=(
        "${OVERLAY_CLIENT_DIR}/logs/EDMC-ModernOverlay"
        "${ROOT_DIR}/logs/EDMC-ModernOverlay"
    )
    local parent_logs=""
    if parent_logs=$(cd "${ROOT_DIR}/../.." 2>/dev/null && pwd); then
        search_roots+=("${parent_logs}/logs/EDMC-ModernOverlay")
    fi
    search_roots+=(
        "${ROOT_DIR%/*}/logs/EDMC-ModernOverlay"
        "${HOME}/EDMC-ModernOverlay"
        "${HOME}/EDMarketConnector/logs/EDMC-ModernOverlay"
    )

    shopt -s nullglob
    local candidates=()
    for dir in "${search_roots[@]}"; do
        if [[ -d "$dir" ]]; then
            for file in "$dir"/overlay-client.log*; do
                [[ -f "$file" ]] && candidates+=("$file")
            done
        fi
    done
    shopt -u nullglob

    if ((${#candidates[@]} == 0)); then
        return 1
    fi

    for file in "${candidates[@]}"; do
        local ts
        ts=$(stat -c '%Y' "$file" 2>/dev/null || printf '0')
        printf '%s\t%s\n' "$ts" "$file"
    done | sort -nr | cut -f2-
    return 0
}

dump_json() {
    local label="$1"
    local path="$2"
    print_header "$label"
    if [[ ! -f "$path" ]]; then
        printf 'Unable to read %s: missing\n' "$label"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        if ! python3 - "$path" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as handle:
    data = json.load(handle)
print(json.dumps(data, indent=2, sort_keys=True))
PY
        then
            printf 'Unable to read %s: invalid JSON or read error\n' "$label"
        fi
    else
        cat "$path"
    fi
}

print_logs() {
    print_header "Overlay Client Logs"
    local sorted=()
    if ! mapfile -t sorted < <(gather_overlay_log_candidates); then
        echo "No overlay-client logs found in standard locations."
        return
    fi
    local latest="${sorted[0]}"
    local latest_display
    latest_display="$(abbrev_path "$latest")"
    printf 'Latest log: %s\n' "$latest_display"
    if [[ -f "$latest" ]]; then
        if [[ -n "${HOME:-}" && "$HOME" != "/" ]]; then
            tail -n "$LOG_LINES" "$latest" 2>/dev/null | sed "s#${HOME}#~#g" | sed 's/^/  /'
        else
            tail -n "$LOG_LINES" "$latest" 2>/dev/null | sed 's/^/  /'
        fi
    else
        echo "  <unable to read log file>"
    fi
}

print_debug_overlay_snapshot() {
    print_header "Debug Overlay Snapshot"
    local sorted=()
    if ! mapfile -t sorted < <(gather_overlay_log_candidates); then
        echo "No overlay-client logs found in standard locations."
        return
    fi
    if ((${#sorted[@]} == 0)); then
        echo "No overlay-client logs found in standard locations."
        return
    fi
    local latest="${sorted[0]}"
    if [[ ! -f "$latest" ]]; then
        echo "Latest overlay-client log missing; unable to extract debug overlay information."
        return
    fi

    local output
    if ! output=$(python3 - "$latest" "$SETTINGS_PATH" <<'PY'
import json
import re
import sys
from pathlib import Path

log_path = Path(sys.argv[1])
settings_path = Path(sys.argv[2])
home_path = str(Path.home())

def abbreviate(path):
    path = str(path)
    if home_path and path.startswith(home_path):
        return "~" + path[len(home_path):]
    return path

try:
    settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
except Exception:
    settings_data = {}

min_font = float(settings_data.get("min_font_point", 6.0))
max_font = float(settings_data.get("max_font_point", 18.0))

patterns = {
    "move": re.compile(
        r"Overlay moveEvent: pos=\((?P<pos>[^)]*)\) frame=\((?P<frame>[^)]*)\) .*? monitor=(?P<monitor>[^;]+);\s*size=(?P<size>[0-9]+x[0-9]+)px scale_x=(?P<scale_x>[0-9.]+) scale_y=(?P<scale_y>[0-9.]+)"
    ),
    "tracker": re.compile(
        r"Tracker state: id=(?P<id>0x[0-9a-fA-F]+) global=\((?P<global>[^)]*)\) size=(?P<size>[0-9]+x[0-9]+) .*?; size=(?P<overlay>[0-9]+x[0-9]+)px scale_x=(?P<scale_x>[0-9.]+) scale_y=(?P<scale_y>[0-9.]+)"
    ),
    "raw": re.compile(r"Raw tracker window geometry: pos=\((?P<pos>[^)]*)\) size=(?P<size>[0-9]+x[0-9]+)"),
    "calculated": re.compile(
        r"Calculated overlay geometry: target=\((?P<target>[^)]*)\);\s*size=(?P<size>[0-9]+x[0-9]+)px scale_x=(?P<scale_x>[0-9.]+) scale_y=(?P<scale_y>[0-9.]+)"
    ),
    "wm": re.compile(
        r"Recorded WM authoritative rect \((?P<meta>[^)]*)\): actual=\((?P<actual>[^)]*)\) tracker=(?P<tracker>[^;]+);\s*size=(?P<size>[0-9]+x[0-9]+)px(?: scale_x=(?P<scale_x>[0-9.]+) scale_y=(?P<scale_y>[0-9.]+))?"
    ),
    "scaling": re.compile(
        r"Overlay scaling updated: window=(?P<width>[0-9]+)x(?P<height>[0-9]+) px "
        r"mode=(?P<mode>[a-z]+) base_scale=(?P<base_scale>[0-9.]+) "
        r"scale_x=(?P<scale_x>[0-9.]+) scale_y=(?P<scale_y>[0-9.]+) diag=(?P<diag>[0-9.]+) "
        r"scaled=(?P<scaled_w>[0-9.]+)x(?P<scaled_h>[0-9.]+) "
        r"offset=\((?P<offset_x>-?[0-9.]+),(?P<offset_y>-?[0-9.]+)\) "
        r"overflow_x=(?P<overflow_x>[01]) overflow_y=(?P<overflow_y>[01]) message_pt=(?P<message>[0-9.]+)"
    ),
    "title_offset": re.compile(
        r"Title bar offset updated: enabled=(?P<enabled>True|False) height=(?P<height>[0-9]+) offset=(?P<offset>-?[0-9]+) scale_y=(?P<scale_y>[0-9.]+)"
    ),
}

latest = {key: None for key in patterns}

with log_path.open("r", encoding="utf-8", errors="replace") as handle:
    for line in handle:
        for key, pattern in patterns.items():
            if key == "move" and "Overlay moveEvent:" not in line:
                continue
            if key == "tracker" and "Tracker state:" not in line:
                continue
            if key == "raw" and "Raw tracker window geometry:" not in line:
                continue
            if key == "calculated" and "Calculated overlay geometry:" not in line:
                continue
            if key == "wm" and "Recorded WM authoritative rect" not in line:
                continue
            if key == "scaling" and "Overlay scaling updated:" not in line:
                continue
            if key == "title_offset" and "Title bar offset updated:" not in line:
                continue
            match = pattern.search(line)
            if match:
                latest[key] = match.groupdict()

def parse_rect(text):
    try:
        parts = [int(p.strip()) for p in text.split(",")]
        if len(parts) == 4:
            return parts
    except Exception:
        pass
    return None

def parse_point(text):
    try:
        parts = [int(p.strip()) for p in text.split(",")]
        if len(parts) == 2:
            return parts
    except Exception:
        pass
    return None

def parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

lines = [f"Source log: {abbreviate(log_path)}"]

move_info = latest.get("move")
tracker_info = latest.get("tracker")
wm_info = latest.get("wm")
raw_info = latest.get("raw")
calc_info = latest.get("calculated")
scaling_info = latest.get("scaling")
title_info = latest.get("title_offset")

scaling_mode = None
scaling_base = None
scaling_scale_x = None
scaling_scale_y = None
scaling_diag = None
scaling_scaled_w = None
scaling_scaled_h = None
scaling_offset_x = None
scaling_offset_y = None
scaling_overflow_x = None
scaling_overflow_y = None
scaling_message = None

if scaling_info:
    raw_mode = (scaling_info.get("mode") or "").strip()
    scaling_mode = raw_mode if raw_mode else None
    scaling_base = parse_float(scaling_info.get("base_scale"))
    scaling_scale_x = parse_float(scaling_info.get("scale_x"))
    scaling_scale_y = parse_float(scaling_info.get("scale_y"))
    scaling_diag = parse_float(scaling_info.get("diag"))
    scaling_scaled_w = parse_float(scaling_info.get("scaled_w"))
    scaling_scaled_h = parse_float(scaling_info.get("scaled_h"))
    scaling_offset_x = parse_float(scaling_info.get("offset_x"))
    scaling_offset_y = parse_float(scaling_info.get("offset_y"))
    scaling_overflow_x = scaling_info.get("overflow_x")
    scaling_overflow_y = scaling_info.get("overflow_y")
    scaling_message = parse_float(scaling_info.get("message"))

lines.append("Monitor:")
if move_info:
    monitor_label = (move_info.get("monitor") or "").strip() or "unknown"
    lines.append(f"  active={monitor_label}")
else:
    lines.append("  active=<unavailable>")

if tracker_info:
    tracker_point = parse_point(tracker_info.get("global", ""))
    tracker_size = tracker_info.get("size", "")
    overlay_size = tracker_info.get("overlay", "")
    scale_x = tracker_info.get("scale_x")
    scale_y = tracker_info.get("scale_y")
    parts = []
    if tracker_point and tracker_size:
        parts.append(f"({tracker_point[0]},{tracker_point[1]}) {tracker_size}")
    if overlay_size:
        parts.append(f"overlay={overlay_size}")
    if scale_x and scale_y:
        parts.append(f"scale={float(scale_x):.2f}x{float(scale_y):.2f}")
    lines.append(f"  tracker={' '.join(parts) if parts else '<unavailable>'}")
else:
    lines.append("  tracker=<unavailable>")

if wm_info:
    actual_rect = parse_rect(wm_info.get("actual", ""))
    meta = wm_info.get("meta", "")
    classification = None
    if "classification=" in meta:
        classification = meta.split("classification=", 1)[-1].strip()
    tracker_rect = wm_info.get("tracker", "").strip()
    if actual_rect:
        rect_desc = f"({actual_rect[0]},{actual_rect[1]}) {actual_rect[2]}x{actual_rect[3]}"
    else:
        rect_desc = wm_info.get("actual", "").strip() or "<unavailable>"
    suffix = f" [{classification}]" if classification else ""
    lines.append(f"  wm_rect={rect_desc}{suffix}")
    if tracker_rect and tracker_rect.lower() != "none":
        lines.append(f"  wm_tracker={tracker_rect}")
else:
    lines.append("  wm_rect=<unavailable>")

lines.append("")
lines.append("Overlay:")
if calc_info:
    rect = parse_rect(calc_info.get("target", ""))
    if rect:
        lines.append(f"  frame=({rect[0]},{rect[1]}) {rect[2]}x{rect[3]}")
    else:
        lines.append(f"  frame={calc_info.get('target', '<unavailable>')}")
    size_desc = calc_info.get("size")
    if size_desc:
        lines.append(f"  widget={size_desc}")
    scale_x = calc_info.get("scale_x")
    scale_y = calc_info.get("scale_y")
    if scale_x and scale_y:
        lines.append(f"  calc_scale={float(scale_x):.2f}x{float(scale_y):.2f}")
else:
    lines.append("  frame=<unavailable>")

if raw_info:
    raw_point = parse_point(raw_info.get("pos", ""))
    raw_size = raw_info.get("size", "")
    if raw_point:
        lines.append(f"  raw=({raw_point[0]},{raw_point[1]}) {raw_size}")
    else:
        lines.append(f"  raw={raw_info.get('pos', '<unavailable>')} {raw_size}")
else:
    lines.append("  raw=<unavailable>")

if move_info:
    move_size = move_info.get("size")
    move_scale_x = move_info.get("scale_x")
    move_scale_y = move_info.get("scale_y")
    if move_size and move_scale_x and move_scale_y:
        lines.append(f"  move_event={move_size} scale={float(move_scale_x):.2f}x{float(move_scale_y):.2f}")

lines.append("")
lines.append("Scaling:")
if scaling_info:
    mode_label = scaling_mode or "<unknown>"
    if scaling_base is not None:
        lines.append(f"  mode={mode_label} base_scale={scaling_base:.4f}")
    else:
        lines.append(f"  mode={mode_label}")
    if scaling_scale_x is not None and scaling_scale_y is not None:
        lines.append(f"  physical_scale={scaling_scale_x:.3f}x{scaling_scale_y:.3f}")
    if (
        scaling_scaled_w is not None
        and scaling_scaled_h is not None
        and scaling_offset_x is not None
        and scaling_offset_y is not None
    ):
        lines.append(
            "  scaled_canvas={:.1f}x{:.1f} offset=({:.1f},{:.1f})".format(
                scaling_scaled_w,
                scaling_scaled_h,
                scaling_offset_x,
                scaling_offset_y,
            )
        )
    if scaling_overflow_x is not None and scaling_overflow_y is not None:
        overflow_x = "yes" if str(scaling_overflow_x) == "1" else "no"
        overflow_y = "yes" if str(scaling_overflow_y) == "1" else "no"
        lines.append(f"  overflow_x={overflow_x} overflow_y={overflow_y}")
else:
    lines.append("  mode=<unavailable>")

lines.append("")
lines.append("Fonts:")
if (
    scaling_scale_x is not None
    and scaling_scale_y is not None
    and scaling_diag is not None
    and scaling_message is not None
):
    lines.append(f"  scale_x={scaling_scale_x:.2f} scale_y={scaling_scale_y:.2f} diag={scaling_diag:.2f}")
    lines.append(f"  ui_scale={scaling_diag:.2f}")
    lines.append(f"  bounds={min_font:.1f}-{max_font:.1f}")
    lines.append(f"  message={scaling_message:.1f}")
    normal_point = max(min_font, min(max_font, 10.0 * scaling_diag))
    small_point = max(1.0, normal_point - 2.0)
    large_point = max(1.0, normal_point + 2.0)
    huge_point = max(1.0, normal_point + 4.0)
    lines.append(f"  status={normal_point:.1f}")
    lines.append(f"  legacy={normal_point:.1f}")
    lines.append(
        "  legacy presets: S={:.1f} N={:.1f} L={:.1f} H={:.1f}".format(
            small_point, normal_point, large_point, huge_point
        )
    )
else:
    if scaling_scale_x is not None and scaling_scale_y is not None and scaling_diag is not None:
        lines.append(f"  scale_x={scaling_scale_x:.2f} scale_y={scaling_scale_y:.2f} diag={scaling_diag:.2f}")
    else:
        lines.append("  scale_x=<unavailable> scale_y=<unavailable> diag=<unavailable>")
    if scaling_diag is not None:
        lines.append(f"  ui_scale={scaling_diag:.2f}")
    else:
        lines.append("  ui_scale=<unavailable>")
    lines.append(f"  bounds={min_font:.1f}-{max_font:.1f}")
    if scaling_message is not None:
        lines.append(f"  message={scaling_message:.1f}")
    else:
        lines.append("  message=<unavailable>")
    lines.append("  status=<unavailable>")
    lines.append("  legacy=<unavailable>")
    lines.append("  legacy presets: <unavailable>")

title_enabled = bool(settings_data.get("title_bar_enabled", False))
try:
    title_height = int(settings_data.get("title_bar_height", 0))
except (TypeError, ValueError):
    title_height = 0

lines.append("")
lines.append("Settings:")
lines.append(f"  title_bar_compensation={'on' if title_enabled else 'off'} height={title_height}")
applied_line = None
if title_info:
    try:
        applied_offset = int(title_info.get("offset", "0"))
    except (TypeError, ValueError):
        applied_offset = None
    scale_value = title_info.get("scale_y")
    if applied_offset is not None:
        if scale_value:
            try:
                applied_line = f"  applied_offset={applied_offset} scale_y={float(scale_value):.2f}"
            except (TypeError, ValueError):
                applied_line = f"  applied_offset={applied_offset}"
        else:
            applied_line = f"  applied_offset={applied_offset}"
if applied_line is None:
    applied_line = "  applied_offset=<unavailable>"
lines.append(applied_line)

print("\n".join(lines))
PY
); then
        echo "Unable to extract debug overlay information from ${latest}."
        return
    fi
    printf '%s\n' "$output"
}

print_notes() {
    print_header "Notes"
    cat <<'EOF'
Share this output when reporting overlay issues. Sensitive data is not collected, but review
the log snippet before sharing if you have concerns.
EOF
}

clear
printf 'EDMC Modern Overlay - Environment Snapshot\n'
printf 'Generated by collect_overlay_debug_linux.sh\n'

print_system_info
print_environment
print_command_availability
check_required_packages
check_virtualenv
check_python_modules
print_debug_overlay_snapshot
dump_json "overlay_settings.json" "$SETTINGS_PATH"
dump_json "port.json" "$PORT_PATH"
if (( SHOW_LOGS )); then
    print_logs
else
    printf '\n(Overlay client logs omitted; re-run with --show-logs to include them.)\n'
fi
print_notes

exit 0
