# Project Summary (Late November 2025)

This file captures the high-level state after the recent enhancements so we can restart with minimal context.

## Major Features Delivered

- **Live Scan Telemetry**
  - `ScanProgress` includes `phase` (`walking`, `aggregating`, `grouping`) and `last_path`, plus streaming folder/file counts.
  - Frontend progress card shows counters, a weighted overall progress bar, an indeterminate activity indicator for the walking phase, percentage-based phase progress for aggregating/grouping, and elapsed/ETA labels.
- **Diff Endpoint & Modal**
  - REST: `GET /api/scans/{scan_id}/groups/{group_id}/diff` returns `only_left`, `only_right`, and `mismatched` entries (derived from aggregated fingerprints).
  - UI exposes “Compare” per near-duplicate member; modal renders side-by-side differences with byte stats.
- **Similarity Group Tree View**
  - Added List/Tree toggle. Tree aggregates bytes, identical/near counts, and reclaimable bytes per folder; supports search + expand/collapse.
  - Tree shows only canonical/reference folders as nodes; duplicates are surfaced inline per row and in the comparison panel.
- **Visual Insights & Comparison**
  - Similarity Matrix view backed by `GET /api/scans/{scan_id}/matrix`, showing top-K adjacency pairs with a heatmap-like list.
  - Duplicate-density Treemap backed by `GET /api/scans/{scan_id}/density/treemap`, summarizing duplicate bytes per folder hierarchy.
  - Folder Comparison panel renders canonical + duplicates side-by-side, with a file-explorer-style list for each member and color-coded highlights for unique and mismatched entries; includes a toggle to hide/show matching files. The comparison view now uses a single shared scrollbar and resizable, window-aware columns so large folders remain easy to scan.
- **Memory Instrumentation + Lightweight Models**
  - Scanner, grouping, and analytics now operate on lightweight dataclasses (`FolderInfo`, `GroupInfo`) rather than pydantic models, dramatically reducing transient allocations; pydantic objects are only materialized at the REST boundary.
  - Fingerprints are persisted to a shelve-backed store once grouping completes so scans no longer keep entire fingerprint maps in RAM.
  - Grouping no longer maintains an O(N²) visited-pairs set and uses a streaming weighted Jaccard calculation, cutting peak RSS on `test_mockup` from ~1.7 GiB down to ~54 MiB and reducing grouping time from ~23 s to ~7 s in the default benchmark run.
  - The benchmark harness gained phase heap snapshots, RSS timelines, smaps/object-census logging, and per-run JSON archives under `docs/benchmark-history/`.
  - The group diff pipeline was hardened so the `/api/scans/{scan_id}/groups/{group_id}/diff` endpoint now converts lightweight `FolderInfo` dataclasses back into Pydantic `FolderRecord` models at the boundary, eliminating 500s from validation errors and ensuring diffs always render in the UI.
- **Diagnostics & Observability**
  - SSE log streaming via `GET /api/system/logs/stream`, wired into a Diagnostics drawer in the UI.
  - Resource snapshot endpoint `GET /api/system/resources` surfaces CPU cores/load, process RSS, and best-effort I/O bytes; diagnostics drawer polls this and shows a live resource strip.
  - Backend scan runner records warnings instead of failing scans when late-phase errors occur, so completed scans remain inspectable even if secondary analytics fail.
- **Push Progress & Metrics**
  - `/api/scans/events` streams scan progress over SSE so the UI updates instantly without the 4s poll loop; the React app auto-reconnects and falls back gracefully.
  - `/api/scans/{scan_id}/metrics` now exposes per-phase durations, bytes scanned, worker allocation, and resource samples captured during each phase.
  - Optional `/metrics` endpoint (gated by `XFS_METRICS_ENABLED=1`) serves Prometheus-compatible gauges for phase durations, bytes scanned, total scans, and active scan counts.

- **Similarity Explorer UI Revamp**
  - The Similarity Explorer now uses a 1/3–2/3 split: a compact list/tree of groups on the left and a window-aware Folder Comparison on the right, with a draggable splitter for power users.
  - Group rows were flattened into a denser, “explorer-like” table: the Status column stacks label, similarity, reclaimable bytes, and stability; Folder shows the canonical path and counts; Members contains the selectable duplicates and Compare actions.
  - Column widths were relaxed and rely on the container width instead of fixed pixel widths, eliminating the horizontal “jump” when toggling between 2- and 3-way comparisons.
  - Folder Comparison cards resize with the viewport, with a single vertical scrollbar for the entire comparison and truncated paths to keep the layout stable even for deep trees.

- **Top-Level Dashboard Layout**
  - The “New Scan” panel now uses a single vertical field stack, making the scan form easier to skim and tweak.
  - “Active Scans” and the metrics cards were moved into a shared right-hand panel, opposite New Scan, so you always see the launch controls and current scan list side by side.
  - The active scans table scrolls within a fixed-height panel that matches the New Scan height, and the summary metric cards sit directly beneath it, giving the whole top section a compact, consistent dashboard feel.

## Recent Fixes

- **Parent-Level Similarity Groups**
  - When scanning with `structure_policy="relative"`, identical or near-identical sibling folders (e.g., `B/`, `C/`, `D/`) now collapse into a single parent-level group instead of surfacing separate child groups.
  - Canonical selection prefers the shallowest, most-connected folder in the cluster, and descendant groups are suppressed once their parents are grouped.

## Key Tests / Validation

- Backend unit suite (`backend/tests/`) covers nested identicals, threshold demotion, empty trees, unique files, ancestor suppression (identical & near). Command: `PYTHONPATH=app .venv/bin/python -m pytest -q`.
- Manual checklist (`docs/test.md`): progress telemetry, diff modal, tree view behavior, deletion workflow, frontend build.

## Next Steps / Roadmap

1. **Adaptive Scaling & Pruning**: now that per-phase timings and bytes scanned are recorded, teach the scheduler to raise/lower worker counts and tweak candidate pruning thresholds based on live metrics, especially on >10M file trees. Build on the new dataclass/fingerprint-store pipeline so the scheduler can spill group chunks to disk without rehydrating pydantic models.
2. **Progress Channel Polish**: expand the SSE stream with scan-level diff summaries (e.g., recently completed groups) and add pagination-aware deltas so very large scan lists don’t flood the client; document proxy/timeout guidance for operators.
3. **Operations & Alerting**: ship Grafana-ready dashboards for the new metrics, describe alert thresholds (active scan saturation, slow phases), and add CLI helpers that dump `/api/scans/{scan_id}/metrics` snapshots for support cases.

## Implementation Plan

### 1. Adaptive Scaling & Pruning
- **Backend**: leverage the new phase timings/bytes stats to auto-adjust worker counts and quick-sketch thresholds mid-scan; expose tunables via `ScanRequest` so ops can cap CPU impact for noisy neighbors.
- **Frontend**: add a lightweight “Performance” drawer per scan metrics view so operators can see how concurrency changed over time.
- **Validation**: synthesize large mock trees in `backend/tests/` to prove adaptive tuning keeps throughput consistent while respecting CPU limits.

### 2. Progress Channel Enhancements
- **Backend**: enrich the SSE payload with incremental change sets (state + deltas) so future UIs can virtualize scan lists; add heartbeat events and document recommended proxy timeouts for long connections.
- **Frontend**: introduce a `useScanEvents` hook that buffers SSE traffic and hydrates local caches, plus toast warnings when the stream reconnects repeatedly.
- **Validation**: expand Vitest/MSW coverage for SSE reconnects and add a manual check that toggling between networks doesn’t drop state.

### 3. Metrics Dashboards & Alerts
- **Backend**: publish example Prometheus recording rules for slow phases/overdue scans, add histogram buckets for long-running phases, and expose a support CLI that snapshots `/api/scans/{scan_id}/metrics`.
- **Docs/Tooling**: provide Grafana JSON dashboards + runbooks for alert tuning, and link them from `docs/test.md` so QA covers observability wiring.
- **Validation**: run `pytest -q tests/test_api_endpoints.py` plus end-to-end drills that hit `/metrics` from a Prometheus container.

Refer to this summary along with `docs/prd.md` (requirements) and `docs/test.md` (QA plan) when rebooting work.
