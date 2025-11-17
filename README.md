# Folder Similarity Scanner

Container-ready folder similarity scanner that follows the **Folder Similarity Scanner — Specification v2.1**. The system scans a root directory, computes byte-weighted similarity between folders, and surfaces identical or near-duplicate structures in an interactive web UI. A guarded deletion workflow lets you quarantine redundant folders after previewing the impact.

## Architecture

- **Backend**: FastAPI service (`backend/app`) responsible for walking the filesystem, hashing files (with optional SHA-256), computing weighted Jaccard similarity, caching file fingerprints in SQLite, serving REST endpoints, and orchestrating the deletion/quarantine workflow.
- **Frontend**: React + Vite single-page application (`frontend/`) bundled into static assets and served by the backend. The UI presents scan health, duplicate clusters, exports, warnings, and deletion tooling.
- **Container**: Single Docker image exposing port `8080`. Bind-mounts allow read-only or read/write scans, plus a config volume for caches.

## Requirements

- Python 3.11+
- Node.js 18+ (for building the UI)
- npm
- Optional: Docker 24+

## Quick Start (local dev)

```bash
# Install backend deps
cd backend
pip install -r requirements.txt

# Run backend API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

# In a separate shell, install + run the frontend dev server
cd ../frontend
npm install
npm run dev  # proxies /api to localhost:8080
```

The dev UI is available at <http://localhost:5173>. The backend serves `http://localhost:8080/api/...`.

## Containerized Deployment

```bash
# Build the image
docker build -t xfolder:latest .

# Run a read-only scan container
docker run --rm \
  -p 8080:8080 \
  -v /host/data:/data:ro \
  -v /host/config:/config:rw \
  xfolder:latest \
  uvicorn app.main:app --host 0.0.0.0 --port 8080
```

For deletion/quarantine support, remount the data volume read/write (`:rw`). Quarantine lives under `<root>/.folderdupe_quarantine/YYYYMMDD`.

### Docker Compose snippet

```yaml
services:
  xfolder:
    image: xfolder:latest
    ports:
      - "8080:8080"
    environment:
      - XFS_CONFIG_PATH=/config
      - XFS_LOG_LEVEL=INFO
      - XFS_LOG_STREAM_ENABLED=1  # enable diagnostics drawer streaming
    volumes:
      - /host/data:/data:rw          # switch to :ro for read-only scans
      - /host/config:/config:rw
```

## Using the UI

1. Launch a scan: choose the root path (`/data` by default), pick equality mode (`name_size` or `sha256`), adjust similarity threshold, and decide if deletion is enabled.
2. Monitor scan progress and warnings in **Active Scans**.
3. Once completed, browse **Similarity Groups**:
   - **Identical**: perfect clones (1.0 similarity).
   - **Near Duplicate**: ≥0.80 similarity.
   - **Overlap Explorer**: partial overlaps (future extension).
4. Select redundant members and hit **Plan Quarantine** to stage a deletion plan. A second **Confirm & Move** step moves items into the quarantine directory.
5. Exports: download JSON, CSV, or Markdown views for offline triage or audit trails.

## REST API Highlights

- `POST /api/scans` — start a scan (`ScanRequest` body).
- `GET /api/scans` — list scan jobs and progress.
- `GET /api/scans/{scan_id}/groups?label=identical` — fetch similarity groups.
- `POST /api/scans/{scan_id}/export?fmt=csv` — export groups (JSON/CSV/Markdown).
- `POST /api/scans/{scan_id}/deletion/plan` — generate a deletion plan (`{"paths": [...]}`).
- `POST /api/deletions/{plan_id}/confirm` — confirm planned deletion (`{"token": "..."}`).

All payload schemas mirror the PRD section 12.

## Configuration

Environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `XFS_LISTEN_HOST` | `0.0.0.0` | HTTP bind address |
| `XFS_LISTEN_PORT` | `8080` | HTTP port |
| `XFS_CONFIG_PATH` | `/config` | Persistent config/cache directory |
| `XFS_CACHE_DB` | `<config>/cache.db` | Override cache database path |

Runtime defaults align with the PRD: similarity threshold 0.80, `name_size` equality, relative structure, and case sensitivity matching the underlying filesystem.

## Testing & Validation

- **Backend sanity**: `python3 -m compileall backend/app`
- **Backend unit tests**: `make test-backend` (uses pytest fixtures to synthesize nested duplicate trees, including ancestor/descendant layouts).
- **Run a sample scan**: mount a test directory and call `POST /api/scans` with JSON payload using `curl` or the UI.
- **Frontend lint**: `npm run build` (build step catches TS errors).
- **Headless benchmark**: see `docs/benchmark.md` for the automated script that scans `test_mockup/` and reports per-phase timings + RAM usage.

## Operational Notes

- Hash cache stored in SQLite under `/config/cache.db` (adjust via `XFS_CACHE_DB`).
- Hard links are deduplicated per `(device, inode)`.
- Deletion requires read/write mount; the API enforces root confinement and quarantine retention (30 days by default, purge via future UI action).
- Event watching is explicit rescan only—no inotify/fanotify usage per PRD.

Refer to `docs/prd.md` for the authoritative specification the implementation follows.
