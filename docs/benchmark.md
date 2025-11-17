# Benchmark Procedure

This guide explains how to run the Folder Similarity Scanner in a headless mode against the standardized `test_mockup/` dataset and capture benchmark metrics (phase timings and memory usage).

## Dataset

- The repository ships `test_mockup/` at the root. It exercises common similarity scenarios (identical photos, near matches, sparse trees, etc.) and is safe to scan locally.
- The benchmark script defaults to this directory, so no additional fixtures or paths are required.

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

The script starts a `ScanManager`, waits for completion, and prints per-phase timings plus peak/average RSS gathered from `resource_samples`. It also reports each resource-sample timestamp and highlights the phase-specific memory peaks so you can pinpoint when the RAM surge occurs.

## Latest Recorded Results

- **Command**: `backend/.venv/bin/python backend/scripts/run_benchmark.py --json-output`
- **Date**: 2025-11-17
- **Target**: `/home/alex/Work/Projects/xfolder/test_mockup`
- **Insights**: Similarity matrix + treemap disabled (default settings)

| Phase | Duration (s) |
| --- | --- |
| walking | 0.39 |
| aggregating | 0.13 |
| grouping | 24.27 |

Additional metrics:

| Metric | Value |
| --- | --- |
| Total wall time | 24.79 s |
| Peak RSS | 1.68 GiB (1717.20 MiB) |
| Average RSS | 0.33 GiB (333.37 MiB) |
| Resource samples captured | 6 |
| Folders scanned | 6,118 |

Every invocation now writes a JSON summary to `docs/benchmark-history/` (name includes the scan id and timestamp) unless `--no-log` is specified. Use these files to compare runs over time and correlate RAM deltas with code changes.
