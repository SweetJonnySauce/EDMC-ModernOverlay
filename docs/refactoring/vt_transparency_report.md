VirusTotal Transparency Report Plan
===================================

Goal: Publish VirusTotal results for every release asset in one place, even when multiple VT jobs run separately.

Constraints and pain points
- Two VT runs per release today (zip/tar + installer) create separate badges; release notes only update after the last run, which is fragile if a job retries or fails.
- We must avoid editing release notes from multiple jobs to prevent badge loss or duplication.
- Keep the report concise (badges + links), but include failing assets for transparency.

- Plan (minimal changes)
- Release notes must be updated only after all VT jobs complete successfully.
- Per VT job:
  - After scanning, write a small markdown fragment `badges.md` containing one badge line per scanned asset (with asset name prefix and VT link).
  - Upload `badges.md` as an artifact named `vt-report-<job>` (unique per workflow invocation).
- Aggregation job (new):
  - Needs all VT jobs.
  - Downloads every `vt-report-*` artifact into a temp folder.
  - Concatenates them into `vt-transparency.md` (add a short heading and timestamp).
  - Attaches `vt-transparency.md` to the release and appends a single link in release notes: e.g., “VirusTotal transparency report”.
- Optional: Also upload `vt-transparency.md` as a build artifact for non-release runs (manual/branch) so we can inspect without touching release notes.
- Add a reusable markdown header template (e.g., `docs/refactoring/vt_report_header.md`) that the aggregator prepends to `vt-transparency.md` so reports start with a consistent intro/context.

Notes on implementation
- Keep release-note edits centralized in the aggregator; individual VT jobs no longer touch release notes directly.
- Badge rendering: use shields.io `/badge/<label>/<msg>/<color>.svg` with the escape rules already in `virustotal_scan.yml`.
- If a VT job fails (malicious/suspicious), still emit its `badges.md` so the report shows the failure; let the job exit non-zero so the release is blocked unless intentionally overridden.
