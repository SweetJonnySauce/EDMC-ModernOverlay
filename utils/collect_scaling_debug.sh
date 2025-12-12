#!/usr/bin/env bash

# collect_scaling_debug.sh - gather display scaling/DPI settings across desktops.

set -u
IFS=$'\n\t'

OUTPUT_PATH=""
TEE_OUTPUT=0

usage() {
    cat <<'EOF'
Usage: collect_scaling_debug.sh [--output PATH] [--tee]

Gather desktop scaling/DPI settings for GNOME, Cinnamon, MATE, KDE/Plasma, XFCE, and
general X11/Wayland environments. Outputs to stdout by default or to a file.

Options:
  -o, --output PATH   Write results to PATH.
      --tee           Write to PATH (if provided) and stdout.
  -h, --help          Show this help message.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--output)
            shift || { echo "Missing argument for --output" >&2; exit 1; }
            OUTPUT_PATH="${1:-}"
            ;;
        --tee)
            TEE_OUTPUT=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
    shift || break
done

if [[ -n "$OUTPUT_PATH" ]]; then
    mkdir -p "$(dirname "$OUTPUT_PATH")" 2>/dev/null || true
    if [[ $TEE_OUTPUT -eq 1 ]]; then
        exec > >(tee "$OUTPUT_PATH")
    else
        exec >"$OUTPUT_PATH"
    fi
fi

print_section() {
    printf '\n== %s ==\n' "$1"
}

run_probe() {
    local title="$1"
    shift
    local cmd=("$@")
    local bin="${cmd[0]}"
    echo "$title:"
    if ! command -v "$bin" >/dev/null 2>&1; then
        printf '  (%s not found)\n' "$bin"
        return
    fi
    local output status
    if output="$("${cmd[@]}" 2>&1)"; then
        if [[ -z "$output" ]]; then
            echo "  (no output)"
        else
            echo "$output"
        fi
    else
        status=$?
        if [[ -n "$output" ]]; then
            echo "$output"
        fi
        printf '  (command exited with status %d)\n' "$status"
    fi
}

GSET_SCHEMAS=""
if command -v gsettings >/dev/null 2>&1; then
    GSET_SCHEMAS="$(gsettings list-schemas 2>/dev/null || true)"
fi

print_gsettings_block() {
    local schema="$1"
    shift
    if [[ -z "$GSET_SCHEMAS" ]]; then
        echo "$schema: gsettings not available"
        return
    fi
    if ! grep -qx "$schema" <<<"$GSET_SCHEMAS"; then
        echo "$schema: schema not present"
        return
    fi
    echo "$schema:"
    local key value
    for key in "$@"; do
        if value="$(gsettings get "$schema" "$key" 2>&1)"; then
            printf '  %s: %s\n' "$key" "$value"
        else
            printf '  %s: <unavailable>\n' "$key"
        fi
    done
}

print_kde_key() {
    local label="$1"
    local file="$2"
    local group="$3"
    local key="$4"
    if ! command -v kreadconfig5 >/dev/null 2>&1; then
        return
    fi
    local value
    value="$(kreadconfig5 --file "$file" --group "$group" --key "$key" 2>/dev/null || true)"
    if [[ -n "$value" ]]; then
        printf '  %s: %s (file=%s group=%s key=%s)\n' "$label" "$value" "$file" "$group" "$key"
    fi
}

print_xfconf_value() {
    local channel="$1"
    local path="$2"
    if ! command -v xfconf-query >/dev/null 2>&1; then
        return
    fi
    local value
    if value="$(xfconf-query -c "$channel" -p "$path" 2>/dev/null)"; then
        printf '  %s: %s\n' "$path" "$value"
    fi
}

echo "EDMC Modern Overlay - Display Scaling Diagnostics"
echo "Timestamp (UTC): $(date -u '+%Y-%m-%d %H:%M:%S')"

print_section "System"
if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    echo "OS: ${NAME:-unknown} ${VERSION:-}"
    echo "ID: ${ID:-unknown} (like: ${ID_LIKE:-n/a})"
else
    echo "/etc/os-release not found"
fi
run_probe "Kernel" uname -srmo
run_probe "Python" python3 --version

print_section "Session/Display"
echo "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-<unset>}"
echo "XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-<unset>}"
echo "DESKTOP_SESSION=${DESKTOP_SESSION:-<unset>}"
echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<unset>}"
echo "DISPLAY=${DISPLAY:-<unset>}"
echo "QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-<unset>}"
echo "GDK_BACKEND=${GDK_BACKEND:-<unset>}"

print_section "Scaling-related environment"
env | grep -E '^(QT|GDK)_[A-Za-z0-9_]*(SCALE|DPI|FACTOR)|^QT_FONT_DPI|^QT_DEVICE_PIXEL_RATIO|^QT_SCALE_FACTOR_ROUNDING_POLICY|^QT_WAYLAND_DISABLE_WINDOWDECORATION|^QT_QPA_PLATFORM$' | sort || echo "(none)"

print_section "gsettings (GNOME/Cinnamon/MATE)"
if [[ -n "$GSET_SCHEMAS" ]]; then
    print_gsettings_block "org.cinnamon.desktop.interface" scaling-factor text-scaling-factor font-name monospace-font-name
    print_gsettings_block "org.gnome.desktop.interface" scaling-factor text-scaling-factor font-name monospace-font-name
    print_gsettings_block "org.mate.interface" scaling-factor text-scaling-factor font-name monospace-font-name
else
    echo "gsettings not available"
fi

print_section "KDE/Plasma (kreadconfig5)"
if command -v kreadconfig5 >/dev/null 2>&1; then
    print_kde_key "XftDPI" "kdeglobals" "General" "XftDPI"
    print_kde_key "ScaleFactor (KScreen)" "kdeglobals" "KScreen" "ScaleFactor"
    print_kde_key "ScaleFactor (KDE)" "kdeglobals" "KDE" "ScaleFactor"
else
    echo "kreadconfig5 not available"
fi

print_section "XFCE (xfconf-query)"
if command -v xfconf-query >/dev/null 2>&1; then
    print_xfconf_value xsettings /Gdk/WindowScalingFactor
    print_xfconf_value xsettings /Xft/DPI
else
    echo "xfconf-query not available"
fi

print_section "X resources DPI"
run_probe "xrdb -query | grep -i dpi" bash -c 'xrdb -query 2>/dev/null | grep -i dpi || true'

print_section "Monitors (xrandr)"
run_probe "xrandr --listmonitors" xrandr --listmonitors
run_probe "xrandr --current" xrandr --current

print_section "Wayland outputs (if available)"
run_probe "swaymsg -t get_outputs" swaymsg -t get_outputs
run_probe "hyprctl monitors" hyprctl monitors

if [[ -n "${OUTPUT_PATH}" ]]; then
    printf '\nSaved to %s\n' "$OUTPUT_PATH"
fi
