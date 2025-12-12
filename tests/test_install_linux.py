import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SOURCE = (REPO_ROOT / "scripts" / "install_linux.sh").read_text(encoding="utf-8")


def _run_bash(script: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"bash exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result.stdout


def _write_trimmed_installer(tmpdir: str) -> Path:
    """Write a copy of install_linux.sh for sourcing in tests (main guarded by env)."""
    path = Path(tmpdir) / "install_linux_trimmed.sh"
    path.write_text(INSTALLER_SOURCE + ("\n" if not INSTALLER_SOURCE.endswith("\n") else ""), encoding="utf-8")
    path.chmod(0o755)
    matrix_src = REPO_ROOT / "scripts" / "install_matrix.json"
    matrix_dest = Path(tmpdir) / "install_matrix.json"
    matrix_dest.write_text(matrix_src.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_pacman_status_check_marks_installed_and_missing() -> None:
    env = os.environ.copy()
    with tempfile.TemporaryDirectory() as tmpdir:
        pacman_path = Path(tmpdir) / "pacman"
        pacman_path.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$1\" == \"-Q\" || \"$1\" == \"-Qq\" ]]; then\n"
            "  pkg=\"${@: -1}\"\n"
            "  if [[ \"$pkg\" == \"python\" ]]; then exit 0; else exit 1; fi\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        pacman_path.chmod(0o755)
        env["PATH"] = f"{tmpdir}:{env.get('PATH','')}"
        installer_path = _write_trimmed_installer(tmpdir)
        script = f"""
export MODERN_OVERLAY_INSTALLER_IMPORT=1
source "{installer_path}"
PKG_INSTALL_CMD=(pacman -S --noconfirm)
classify_package_statuses python missingpkg
echo "SUPPORTED=$PACKAGE_STATUS_CHECK_SUPPORTED"
echo "OK=${{PACKAGES_ALREADY_OK[*]}}"
echo "INSTALL=${{PACKAGES_TO_INSTALL[*]}}"
echo "DETAIL_PY=${{PACKAGE_STATUS_DETAILS[python]}}"
echo "DETAIL_MISSING=${{PACKAGE_STATUS_DETAILS[missingpkg]}}"
"""
        output = _run_bash(script, env)
    lines = dict(line.split("=", 1) for line in output.strip().splitlines() if "=" in line)
    assert lines.get("SUPPORTED") == "1"
    assert lines.get("OK") == "python"
    assert lines.get("INSTALL") == "missingpkg"
    assert lines.get("DETAIL_PY", "").startswith("installed")
    assert "not installed" in lines.get("DETAIL_MISSING", "")


def test_unknown_manager_marks_status_unsupported() -> None:
    env = os.environ.copy()
    with tempfile.TemporaryDirectory() as tmpdir:
        installer_path = _write_trimmed_installer(tmpdir)
        script = f"""
export MODERN_OVERLAY_INSTALLER_IMPORT=1
source "{installer_path}"
PKG_INSTALL_CMD=(unknown-cmd)
classify_package_statuses python
echo "SUPPORTED=$PACKAGE_STATUS_CHECK_SUPPORTED"
echo "OK=${{PACKAGES_ALREADY_OK[*]}}"
echo "INSTALL=${{PACKAGES_TO_INSTALL[*]}}"
echo "DETAIL_PY=${{PACKAGE_STATUS_DETAILS[python]}}"
"""
        output = _run_bash(script, env)
    lines = dict(line.split("=", 1) for line in output.strip().splitlines() if "=" in line)
    assert lines.get("SUPPORTED") == "0"
    assert lines.get("OK") == ""
    assert lines.get("INSTALL") == "python"
    assert "status check unavailable" in lines.get("DETAIL_PY", "") or "status check unsupported" in lines.get("DETAIL_PY", "")


def test_matrix_helper_emits_compositor_match() -> None:
    env = os.environ.copy()
    with tempfile.TemporaryDirectory() as tmpdir:
        installer_path = _write_trimmed_installer(tmpdir)
        script = f"""
export MODERN_OVERLAY_INSTALLER_IMPORT=1
source "{installer_path}"
output="$(matrix_helper compositor-match wayland kde)"
eval "$output"
echo "FOUND=${{COMPOSITOR_FOUND:-0}}"
echo "ID=${{COMPOSITOR_ID:-}}"
echo "LABEL=${{COMPOSITOR_LABEL:-}}"
echo "MATCH=${{COMPOSITOR_MATCH_JSON:-}}"
echo "OVERRIDES=${{COMPOSITOR_ENV_OVERRIDES_JSON:-}}"
echo "NOTES=${{COMPOSITOR_NOTES[*]:-}}"
echo "PROVENANCE=${{COMPOSITOR_PROVENANCE:-}}"
"""
        output = _run_bash(script, env)
    lines = dict(line.split("=", 1) for line in output.strip().splitlines() if "=" in line)
    assert lines.get("FOUND") == "1"
    assert lines.get("ID") == "kwin-wayland"
    assert "KDE Plasma" in lines.get("LABEL", "")
    assert lines.get("MATCH") == '{"session_types":["wayland"],"desktops":["kde","plasma"],"requires_force_xwayland":false}'
    assert lines.get("OVERRIDES") == '{"QT_AUTO_SCREEN_SCALE_FACTOR":"0","QT_ENABLE_HIGHDPI_SCALING":"0","QT_SCALE_FACTOR":"1"}'
    assert "double-scale" in lines.get("NOTES", "")
    assert "KDE" in lines.get("PROVENANCE", "")


def test_compositor_override_none_skips_selection() -> None:
    env = os.environ.copy()
    with tempfile.TemporaryDirectory() as tmpdir:
        installer_path = _write_trimmed_installer(tmpdir)
        script = f"""
export MODERN_OVERLAY_INSTALLER_IMPORT=1
source "{installer_path}"
COMPOSITOR_OVERRIDE=none
XDG_SESSION_TYPE=wayland
XDG_CURRENT_DESKTOP=kde
select_compositor_profile
echo "SELECTED=${{COMPOSITOR_SELECTED:-0}}"
echo "FOUND=${{COMPOSITOR_FOUND:-0}}"
"""
        output = _run_bash(script, env)
    lines = dict(line.split("=", 1) for line in output.strip().splitlines() if "=" in line)
    assert lines.get("SELECTED") == "0"
    assert lines.get("FOUND") in {"", "0"}
