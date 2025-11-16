# Quality Control Guide

This document tracks the automated and manual checks required to validate the Folder Similarity Scanner.

## 1. Automated Test Matrix

| ID | Scenario | Description | Coverage / Command |
| --- | --- | --- | --- |
| T1 | Nested identical folders | `R → {X, A/X, B/nested/X}` with shared payload; ensures only the `X` folders group as identical and root stays out. | `pytest -q tests/test_similarity_groups.py::test_nested_x_directories_cluster_without_root` |
| T2 | Threshold demotion | Adds `C/X` with extra bytes and raises threshold to 0.90 so it becomes near-duplicate rather than identical. | `pytest -q tests/test_similarity_threshold_prevents_false_matches` |
| T3 | Empty directory isolation | Multiple empty trees must not form duplicate clusters. | `pytest -q tests/test_similarity_groups.py::test_empty_directories_do_not_group` |
| T4 | Unique files | Single-file folders with different names/hashes remain isolated. | `pytest -q tests/test_similarity_groups.py::test_unique_files_remain_isolated` |
| T5 | Parent consolidation (identical) | `R/X/{A,B}` vs `R/Y/{A,B}`: only `X` and `Y` surface, totals include descendants. | `pytest -q tests/test_similarity_groups.py::test_parent_supersedes_children` |
| T6 | Parent consolidation (near duplicate) | Near-identical parents with variant child (`media` vs `media_abstract`) surface once; child identical groups suppressed. | `pytest -q tests/test_similarity_groups.py::test_near_duplicate_parent_suppresses_child_identical` |
| T7 | Diff endpoint | `GET /api/scans/{scan_id}/groups/{group_id}/diff` returns `only_left`, `only_right`, and `mismatched` entries for near duplicates. | *(Add dedicated API test when backend suite expands beyond unit scope.)* |
| T8 | Progress telemetry | Scan progress includes `phase` and `last_path`; stats update during scan. | *(Manual/API check: `GET /api/scans` while scan runs.)* |
| T9 | Tree view rendering | Tree aggregates duplicate stats, honors search, and expand/collapse states. | *(Manual UI verification.)* |
| T10 | Matrix adjacency projection | Similarity matrix flattens adjacency pairs in descending order. | `pytest -q tests/test_visualizations.py::test_similarity_matrix_entries_sorted` |
| T11 | Duplicate-density treemap | Treemap aggregation rolls duplicate bytes up to ancestors. | `pytest -q tests/test_visualizations.py::test_treemap_rolls_up_duplicate_bytes` |
| T12 | Frontend bootstrap | React app renders the landing state without runtime errors (catches use-before-init regressions). | `cd frontend && npm run test` |

Run the full suite after changes:

```bash
cd backend
source .venv/bin/activate   # once per session
PYTHONPATH=app pytest -q
```

## 2. Manual Validation Checklist

- **Frontend build parity**: `cd frontend && npm run build` should pass (catches TypeScript/React integration issues).
- **Progress view**: While a scan runs, confirm folder/file counters increment, phase/last-path update, progress bar advances, and ETA updates.
- **Diff modal**: On a near-duplicate entry, hit **Compare** and verify the modal lists “only in” paths and mismatched sizes.
- **Tree view**: Toggle to Tree, expand nodes, use search, and confirm stats/badges match expectations.
- **Similarity matrix view**: Switch to the Visual Insights → Matrix tab, hover entries, and confirm the percentage, reclaimable bytes, and group ids align with the table view.
- **Duplicate-density treemap**: Switch to the Visual Insights → Treemap tab, ensure the bars roughly match duplicate-heavy folders, and clicking between scans refreshes the hierarchy.
- **Diagnostics drawer**: Open Diagnostics from the header, confirm live logs stream (or that a helpful error message appears if streaming is disabled), and close the drawer.
- **Local scan smoke test**:
  1. Mount the target root (bind SMB/NFS via the host OS).
  2. `cd backend && source .venv/bin/activate`  
     `XFS_CONFIG_PATH=./.config uvicorn app.main:app --reload`
  3. In another terminal: `cd frontend && npm run dev`.
  4. Launch a scan with the mounted root; verify similarity group UI shows consolidated parent folders and relative paths.
- **Deletion workflow**: On a scratch directory with RW access, enable deletion via the scan form, stage a plan, confirm quarantine path is populated under `<root>/.folderdupe_quarantine/YYYYMMDD`.

## 3. Regression Expectations

- Identical/near-duplicate suppression guarantees that once a parent folder is grouped, no descendant group (either identical or near-duplicate) appears independently.
- Canonical folder metrics (bytes, file count) always include the entire subtree due to fingerprint aggregation.
- Relative paths shown in the UI must remain relative to the scan root; absolute paths only appear in exports or API payloads.

## 4. Tooling Notes

- Always activate the virtual environment before running backend tests: `source backend/.venv/bin/activate`.
- Use `make test-backend` as shorthand; it wraps the command above.
- For new scenarios, synthesize fixtures inside `backend/tests/` using the helpers in `tests/utils.py`.
