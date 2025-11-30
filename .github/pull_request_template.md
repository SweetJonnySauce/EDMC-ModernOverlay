## EDMC compliance checks

- [ ] Python baseline matches `docs/compliance/edmc_python_version.txt` (run `python scripts/check_edmc_python.py`; set `ALLOW_EDMC_PYTHON_MISMATCH=1` only for non-release/development work)
- [ ] EDMC Releases/Discussions reviewed for plugin-impacting changes (link or note findings)
- [ ] Monitor gating intact (`monitor.game_running()`/`monitor.is_live_galaxy()` in `load.py`)
- [ ] Folder/plugin naming exception acknowledged or resolved for release (`EDMCModernOverlayDev` vs `EDMCModernOverlay`)

## Summary

- Changes:
- Testing:

