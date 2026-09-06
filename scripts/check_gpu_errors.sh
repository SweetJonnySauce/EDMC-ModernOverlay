#!/usr/bin/env bash
# Scan saved kernel logs once; never follow the journal or change system settings.
set -u
set -o pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
Usage: bash scripts/check_gpu_errors.sh [SINCE [UNTIL]]

Scan the current boot's saved kernel logs for NVIDIA/GPU errors, including
dmaAllocMapping. Defaults to the last four hours, ending now.

Examples:
  bash scripts/check_gpu_errors.sh
  bash scripts/check_gpu_errors.sh '30 minutes ago'
  bash scripts/check_gpu_errors.sh '2026-09-05 17:08:35 -0700' '2026-09-05 17:08:50 -0700'

The scan stops after 30 seconds. Narrow the time window if it times out.
Run with sudo if your account cannot read the system journal.
Exit status: 0 = completed (matches or none); 1 = failed or incomplete scan.
EOF
    exit 0
fi

if (( $# > 2 )); then
    echo 'Too many arguments. Use --help for usage.' >&2
    exit 1
fi

for required_command in journalctl timeout grep; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "Required command not found: $required_command" >&2
        exit 1
    fi
done

scan_since="${1:-4 hours ago}"
scan_until="${2:-now}"
error_pattern='dmaAllocMapping|NVRM|Xid|nvidia-modeset|GPU.*(fault|reset|hang)|flip.*(fail|timeout)|out of memory'

printf 'Scanning current-boot kernel logs from "%s" to "%s" (30-second limit)...\n' "$scan_since" "$scan_until"
timeout --kill-after=2s 30s journalctl -b -k \
    --since "$scan_since" --until "$scan_until" --no-pager -o short-iso \
    | grep --line-buffered -Ei "$error_pattern"
scan_status=("${PIPESTATUS[@]}")

if (( scan_status[0] == 124 || scan_status[0] == 137 )); then
    echo 'Scan timed out; results above may be incomplete. Retry with a narrower time window.' >&2
    exit 1
elif (( scan_status[0] != 0 || scan_status[1] > 1 )); then
    echo 'Scan failed; results above may be incomplete. Check the error above; use sudo if journal access was denied.' >&2
    exit 1
elif (( scan_status[1] == 1 )); then
    echo 'No matching GPU errors found in the accessible logs for this time window.'
else
    echo 'Scan complete. Matching entries are shown above; these alone do not establish the cause of a display problem.'
fi
