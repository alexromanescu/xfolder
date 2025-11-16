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

## Implementation Plan

### 1. Similarity Matrix View
- **Backend**: extend scan persistence to store the top-K adjacency pairs per group (reuse current `pairwise_similarity` computation but flatten into a `matrix` table keyed by `scan_id` + folder ids). Add FastAPI models/routes for `GET /api/scans/{scan_id}/matrix`, supporting pagination, similarity filters, and the existing filter metadata defined in `docs/prd.md`.
- **Frontend**: create a dedicated `SimilarityMatrix` feature (fetch hook + heatmap component) that reads the new endpoint, sorts folders by reclaimable bytes, and links each cell to the existing diff modal for quick inspection.
- **Validation**: add backend unit tests that synthesize adjacency fixtures, API contract tests to verify pagination/suppression, and a manual QA step covering the heatmap rendering plus navigation back to the tree/list views.

### 2. Duplicate-density Treemap
- **Backend**: add an aggregate service plus cached summary blob per scan with per-folder byte totals, identical/near counts, and reclaimable bytes so treemap queries do not recompute heavy stats. Expose `GET /api/scans/{scan_id}/density/treemap` with filters mirroring the matrix endpoint.
- **Frontend**: implement a treemap canvas alongside the Tree/List toggle, offering zoom/pan and color-coding by duplicate density; selecting a node should filter the main group list.
- **Validation**: expand the automated suite with aggregation-accuracy tests (confirm totals respect ignore globs and suppression rules), snapshot a mocked treemap view in Vitest, and append a manual checklist entry verifying zoom/search interactions.

### 3. Enhanced Logging & Diagnostics
- **Backend**: introduce configurable logging verbosity (`XFS_LOG_LEVEL`, streaming toggle) and emit structured events for scan phases, cache hits, and quarantine operations. Provide an opt-in `/api/system/logs` stream (SSE/WebSocket) gated behind the new config.
- **Frontend**: surface a diagnostics drawer under the progress card that subscribes to the log stream, offers filtering/download, and degrades cleanly when logging is off.
- **Validation**: add integration tests that mock the streaming sink, ensure toggles take effect via env overrides, and document a manual step to watch logs while a scan runs. Close with the standard regression pass: `make test-backend` and `npm run build`.

Refer to this summary along with `docs/prd.md` (requirements) and `docs/test.md` (QA plan) when rebooting work.
