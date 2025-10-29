# Installation Guide

This guide walks you through running the Folder Similarity Scanner either locally (for quick testing) or inside a container (for long-running scans). It assumes basic familiarity with the Linux terminal.

---

## 1. Local Development / Quick Testing

### 1.1. Prerequisites
- Python 3.11 or newer
- Node.js 18+ (includes npm)
- Git (to clone the repository)

### 1.2. Clone the Repository
```bash
git clone <repo-url> xfolder
cd xfolder
```

### 1.3. Back-end Setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

- Create a writable config directory (otherwise the app will try to use `/config`):
  ```bash
  mkdir -p .config
  ```

### 1.4. Front-end Setup
```bash
cd ../frontend
npm install
```

### 1.5. Run the Servers
1. **Back-end** (from `backend/`):
   ```bash
   source .venv/bin/activate
   XFS_CONFIG_PATH=./.config uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
   ```
   Leave this terminal running.

2. **Front-end** (new terminal, from `frontend/`):
   ```bash
   npm run dev
   ```

Open your browser at `http://localhost:5173`. Enter the path you wish to scan (any directory your user can read) under “Root Path” and launch a scan.

> **Tip:** To test an SMB/NFS share, mount it on the host first (e.g., `/mnt/share`) and scan that mount point.

### 1.6. Shutting Down
- Stop the front-end dev server (`Ctrl+C`).
- Stop uvicorn (`Ctrl+C` in the backend terminal).
- Deactivate the virtual environment (`deactivate`) if desired.

---

## 2. Container Deployment

### 2.1. Prerequisites
- Docker 24+ (or compatible).
- A folder with the repository contents (`xfolder`).

### 2.2. Build the Image
```bash
cd xfolder
docker build -t xfolder:latest .
```

### 2.3. Prepare Mounts
- **Data root**: the directory you want to scan (e.g., `/mnt/share`). Ensure the host has already mounted SMB/NFS shares.
- **Config/cache**: a writable directory on the host for the SQLite cache (e.g., `/var/lib/xfolder-config`).

### 2.4. Run the Container
**Read-only scan (no deletion/quarantine):**
```bash
docker run --rm \
  -p 8080:8080 \
  -v /mnt/share:/data:ro \
  -v /var/lib/xfolder-config:/config:rw \
  xfolder:latest
```

**Deletion/quarantine enabled:**
```bash
docker run --rm \
  -p 8080:8080 \
  -v /mnt/share:/data:rw \
  -v /var/lib/xfolder-config:/config:rw \
  xfolder:latest
```

The web UI and API are both available at `http://localhost:8080`. Use `/data` as the default root inside the container (it maps to your host path).

### 2.5. Stopping the Container
- Press `Ctrl+C` if running in the foreground, or `docker stop <container-id>` if detached.

---

## 3. Useful Commands

| Purpose | Command |
| --- | --- |
| Back-end unit tests | `cd backend && source .venv/bin/activate && PYTHONPATH=app pytest -q` |
| Front-end production build | `cd frontend && npm run build` |
| Back-end dev server | `XFS_CONFIG_PATH=./.config uvicorn app.main:app --reload --host 0.0.0.0 --port 8080` |
| Docker image build | `docker build -t xfolder:latest .` |
| Docker run (RO) | `docker run --rm -p 8080:8080 -v /mnt/share:/data:ro -v /var/lib/xfolder-config:/config:rw xfolder:latest` |

---

## 4. Troubleshooting

- **Permission errors**: double-check that the user running the app can read the root path and write to the config directory.
- **Mounting SMB/NFS**: the scanner does not mount shares itself. Use system tools (e.g., `mount -t cifs ...`) before running the app.
- **Port conflicts**: change `-p 8080:8080` or Vite’s default port in `frontend/vite.config.ts` if needed.
- **Virtualenv reuse**: re-activate with `source backend/.venv/bin/activate` before running backend commands.

Happy scanning!
