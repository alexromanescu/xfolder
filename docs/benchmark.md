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

The script starts a `ScanManager`, waits for completion, and prints per-phase timings plus peak/average RSS gathered from `resource_samples`.

## Latest Recorded Results

- **Command**: `backend/.venv/bin/python backend/scripts/run_benchmark.py --json-output`
- **Date**: 2025-11-17
- **Target**: `/home/alex/Work/Projects/xfolder/test_mockup`

| Phase | Duration (s) |
| --- | --- |
| walking | 0.37 |
| aggregating | 0.13 |
| grouping | 25.05 |

Additional metrics:

| Metric | Value |
| --- | --- |
| Total wall time | 25.55 s |
| Peak RSS | 1.68 GiB (1717.41 MiB) |
| Average RSS | 0.33 GiB (334.02 MiB) |
| Resource samples captured | 6 |
| Folders scanned | 6,118 |

The JSON payload emitted by `--json-output` is suitable for log storage or regression tracking. Re-run the command whenever you need fresh numbers after engine changes or hardware swaps.
