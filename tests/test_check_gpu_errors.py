"""Exercise the standalone scanner with injected journal output, without EDMC."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_gpu_errors.sh"


def run_scanner(tmp_path, journal_body, *args, timeout_body=None):
    journal = tmp_path / "journalctl"
    journal.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$@" > "$SCAN_ARGS_FILE"\n' + journal_body,
        encoding="utf-8",
    )
    journal.chmod(0o755)
    if timeout_body is not None:
        timeout = tmp_path / "timeout"
        timeout.write_text("#!/bin/bash\n" + timeout_body, encoding="utf-8")
        timeout.chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "SCAN_ARGS_FILE": str(tmp_path / "args"),
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def test_default_scan_is_bounded_and_filters_noise(tmp_path):
    result = run_scanner(
        tmp_path,
        "echo 'ordinary kernel message'\necho \"NVRM: dmaAllocMapping_GM107: can't update VA space for mapping\"\n",
    )
    assert result.returncode == 0, result.stderr
    assert "dmaAllocMapping_GM107" in result.stdout
    assert "ordinary kernel message" not in result.stdout
    assert "Scan complete" in result.stdout
    args = (tmp_path / "args").read_text().splitlines()
    assert args == ["-b", "-k", "--since", "4 hours ago", "--until", "now", "--no-pager", "-o", "short-iso"]


def test_no_matches_reports_accessible_window_and_preserves_timestamps(tmp_path):
    start = "2026-09-05 17:08:35 -0700"
    end = "2026-09-05 17:08:50 -0700"
    result = run_scanner(tmp_path, "echo 'ordinary kernel message'\n", start, end)
    assert result.returncode == 0, result.stderr
    assert "No matching GPU errors found in the accessible logs" in result.stdout
    args = (tmp_path / "args").read_text().splitlines()
    assert args[3] == start
    assert args[5] == end


def test_journal_failure_does_not_report_clean_scan(tmp_path):
    result = run_scanner(tmp_path, "echo 'Permission denied' >&2\nexit 1\n")
    assert result.returncode == 1
    assert "Permission denied" in result.stderr
    assert "Scan failed" in result.stderr
    assert "No matching" not in result.stdout


@pytest.mark.parametrize("status", [124, 137])
def test_timeout_reports_incomplete_results(tmp_path, status):
    result = run_scanner(
        tmp_path, "exit 0\n",
        timeout_body=f"echo 'NVRM: partial result'\nexit {status}\n",
    )
    assert result.returncode == 1
    assert "NVRM: partial result" in result.stdout
    assert "Scan timed out" in result.stderr
    assert "Scan complete" not in result.stdout
