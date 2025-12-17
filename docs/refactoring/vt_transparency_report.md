VirusTotal Transparency Report Plan
===================================

Goal: Publish VirusTotal results for every release asset in one place, even when multiple VT jobs run separately.

Constraints and pain points
- Two VT runs per release today (zip/tar + installer) create separate badges; release notes only update after the last run, which is fragile if a job retries or fails.
- We must avoid editing release notes from multiple jobs to prevent badge loss or duplication.
- Keep the report concise (badges + links), but include failing assets for transparency.

- Plan (option 1: single release workflow with explicit needs)
- Release notes must be updated only after all VT jobs complete successfully.
- Per VT job (now inside release.yml):
  - After scanning, write a small markdown fragment `vt_badges.md` containing one badge line per scanned asset (with asset name prefix and VT link).
  - Upload `vt_badges.md` as an artifact named `vt-report-<release_tag>-<job>` so artifacts are tag-scoped and unique.
- Aggregation job (added to release.yml):
  - Needs all VT jobs (zip/tar VT + Inno EXE VT).
  - Downloads every `vt-report-<release_tag>-*` artifact from the current run.
  - Concatenates them into `vt-transparency.md`, prepending an HTML header template if present at `docs/vt_report_header.html`; otherwise add a default heading with the tag and timestamp.
  - Attaches `vt-transparency.md` to the release and appends a single link in release notes (this job is the only release-note writer).
- Optional: Also upload `vt-transparency.md` as a build artifact for non-release runs (manual/branch) so we can inspect without touching release notes.

Notes on implementation
- Keep release-note edits centralized in the aggregator; individual VT jobs no longer touch release notes directly.
- Badge rendering: use shields.io `/badge/<label>/<msg>/<color>.svg` with the escape rules already in `virustotal_scan.yml`.
- If a VT job fails (malicious/suspicious), still emit its `badges.md` so the report shows the failure; let the job exit non-zero so the release is blocked unless intentionally overridden.
