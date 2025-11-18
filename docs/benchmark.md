# Benchmark Procedure

This guide explains how to run the Folder Similarity Scanner in a headless mode against the standardized `test_mockup/` dataset and capture benchmark metrics (phase timings and memory usage).

## Dataset

- The repository ships `test_mockup/` at the root. It exercises common similarity scenarios (identical photos, near matches, sparse trees, etc.) and is safe to scan locally.
- The benchmark script defaults to this directory, so no additional fixtures or paths are required.
- Inside `test_mockup/`, the `progress_shapes/` subtree adds synthetic edge cases for progress tuning:
  - `walk_heavy_shallow/` contains many small, unique files under a single directory so walking dominates while grouping finds almost no work.
  - `group_heavy_cluster/` contains several near-identical folder copies so grouping dominates despite a relatively light walk.

## Running the Benchmark

1. Install backend dependencies (one-time):

   ```bash
   python3 -m venv backend/.venv
   . backend/.venv/bin/activate
   pip install -r backend/requirements.txt
   ```

   (If you already use `make install-backend` inside an activated virtualenv, you can keep that workflow instead.)

2. Execute the benchmark runner:

   ```bash
   backend/.venv/bin/python backend/scripts/run_benchmark.py --json-output
   ```

   Key options:
   - `--target /path/to/root` overrides the folder to scan (defaults to `<repo>/test_mockup`).
   - `--config-dir PATH` stores the temporary cache/config used for the run (defaults to `<repo>/.benchmark-config`).
   - `--json-output` prints a machine-readable summary in addition to the human table.
   - `--include-matrix` / `--include-treemap` opt in to the heavier analytics stages (both default to off to minimize RAM).
   - `--log-dir DIR` controls where per-run JSON artifacts are stored (defaults to `docs/benchmark-history/`); pass `--no-log` to skip writing history files.
   - `--extra-sample-interval N` enables a high-frequency RSS sampler (seconds between polls) so you can inspect the full memory curve.
   - `--profile-heap` turns on `tracemalloc` and records the top allocation sites at the end of the run.

The script starts a `ScanManager`, waits for completion, and prints per-phase timings plus peak/average RSS gathered from `resource_samples`. High-frequency sampling, object censuses, smaps snapshots, and per-phase heap profiles are available via the optional flags above, giving detailed visibility into when and where memory grows. Each run also records a lightweight progress timeline (`progress_samples`) with overall progress, per-phase ratios, and ETA so you can inspect how the progress curves behave on different mock trees.

## Latest Recorded Results

- **Command**: `backend/.venv/bin/python backend/scripts/run_benchmark.py --json-output`
- **Date**: 2025-11-17
- **Target**: `/home/alex/Work/Projects/xfolder/test_mockup`
- **Insights**: Similarity matrix + treemap disabled (default settings). Grouping no longer keeps an O(N²) visited-pairs set in memory and uses a streaming weighted Jaccard calculation, which keeps RAM nearly flat during the grouping phase.

| Phase | Duration (s) |
| --- | --- |
| walking | 0.36 |
| aggregating | 0.12 |
| grouping | 6.54 |

Additional metrics:

| Metric | Value |
| --- | --- |
| Total wall time | 7.03 s |
| Peak RSS | 0.05 GiB (53.65 MiB) |
| Average RSS | 0.05 GiB (51.73 MiB) |
| Resource samples captured | 6 |
| Folders scanned | 6,118 |

Every invocation now writes a JSON summary to `docs/benchmark-history/` (name includes the scan id and timestamp) unless `--no-log` is specified. Use these files to compare runs over time and correlate RAM deltas with code changes.
