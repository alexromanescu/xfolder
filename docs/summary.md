# Project Summary (Mid-November 2025)

This file captures the high-level state after the recent enhancements so we can restart with minimal context.

## Major Features Delivered

- **Live Scan Telemetry**
  - `ScanProgress` includes `phase` (`walking`, `aggregating`, `grouping`) and `last_path`, plus streaming folder/file counts.
  - Frontend progress card shows counters, progress bar, ETA, and phase details.
- **Diff Endpoint & Modal**
  - REST: `GET /api/scans/{scan_id}/groups/{group_id}/diff` returns `only_left`, `only_right`, and `mismatched` entries (derived from aggregated fingerprints).
  - UI exposes “Compare” per near-duplicate member; modal renders side-by-side differences with byte stats.
- **Similarity Group Tree View**
  - Added List/Tree toggle. Tree aggregates bytes, identical/near counts, and reclaimable bytes per folder; supports search + expand/collapse.
  - Foundation for future Matrix/Treemap views (treemap will color by duplicate density).

## Key Tests / Validation

- Backend unit suite (`backend/tests/`) covers nested identicals, threshold demotion, empty trees, unique files, ancestor suppression (identical & near). Command: `PYTHONPATH=app .venv/bin/python -m pytest -q`.
- Manual checklist (`docs/test.md`): progress telemetry, diff modal, tree view behavior, deletion workflow, frontend build.

## Next Steps / Roadmap

1. **Similarity Matrix View**: implement adjacency endpoint + heatmap for top-K duplicates.
2. **Duplicate-density Treemap**: summary endpoint feeding zoomable treemap.
3. **Enhanced logging**: optional server-side verbosity/log streaming to debug stuck scans.

Refer to this summary along with `docs/prd.md` (requirements) and `docs/test.md` (QA plan) when rebooting work.
