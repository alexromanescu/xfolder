# Folder Similarity Scanner — Specification v2.1

## 0. Scope
Scan a single root folder. Identify subfolders that are identical or near-identical elsewhere under the same root. Compute similarity by bytes. Rank by reclaimable size and similarity. Provide a Web UI (User Interface) to inspect, export, and delete with quarantine.

Non-goals: cross-machine synchronization, deduplicating storage at the filesystem layer, media fingerprinting, content preview.

---

## 1. Platforms and Deployment
- OS: Linux.
- NAS: Synology DSM (DiskStation Manager) supported via container.
- Container: single image exposing port `8080`.
- Mounts:
  - `-v /host/data:/data:ro` for scan by default.
  - `-v /host/data:/data:rw` required for deletion/quarantine.
  - `-v /host/config:/config:rw` for settings and cache.
- Network shares: supported when the host mounts SMB (Server Message Block) or NFS (Network File System) and bind-mounts into the container.
- Event watching: do not rely on inotify/fanotify. Use explicit scans.

---

## 2. Definitions
- File equality modes:
  - `name_size`: file equal iff same relative path and byte size.
  - `sha256`: file equal iff Secure Hash Algorithm 256-bit digest matches.
- Directory similarity: weighted Jaccard by bytes over file identities.
- RW (read-write) mount: a container bind mount with write permissions.
- NFC (Normalization Form C): Unicode normalization used for name compare.

---

## 3. Inputs
- Required: one root path per scan (e.g., `/data`).
- Optional:
  - Include/Exclude globs.
  - File equality mode: `name_size` (default) or `sha256`.
  - Large-file hashing chunk size: 4 MiB when `sha256`.
  - Min similarity threshold: default `0.80`.
  - Concurrency cap: default `min(32, 2×CPU cores)`.
  - Case handling: `force_case_insensitive=false` by default.
  - Structure compare: `relative` (default) or `bag_of_files`.
  - Deletion enable toggle.

---

## 4. File Identity
- Default mode: `name_size`.
- Thorough mode:
  - Hash: SHA-256.
  - Chunked reads: 4 MiB blocks.
  - Early exit on first mismatching chunk for pairwise checks.
- Pipeline per file: `stat → size → (name compare) → (partial read) → hash if enabled`.
- Cache key: `(device, inode, size, mtime, sha256?)`.

---

## 5. Directory Similarity
- Universe: files inside a folder, keyed by selected file identity.
- Each file contributes weight equal to its byte size.
- Similarity formula:  
  `sim(A,B) = Σ_i min(bytes_i(A), bytes_i(B)) / Σ_i max(bytes_i(A), bytes_i(B))`
- Labels:
  - `identical`: `sim = 1.0`
  - `near_duplicate`: `sim ≥ 0.80`
  - `partial_overlap`: otherwise
- Structure policy:
  - Default `relative`: compare by relative paths; folder structure matters.
  - Option `bag_of_files`: ignore paths; compare as multisets of filenames.
- Hierarchy consolidation:
  - Fingerprints roll up descendant file weights so parent folder metrics (bytes, file count) reflect the entire subtree.
  - If a parent folder meets the similarity threshold, suppress any descendant groups (identical or near-duplicate) whose members are wholly contained by that parent cluster.
  - Suppression applies across labels (e.g., identical children under near-duplicate parents).
- Identical folders require both byte totals **and** file counts to match exactly; otherwise the pair is classified as near-duplicate.

---

## 6. Traversal Semantics
- Symlinks: ignore (do not follow).
- Hard links: collapse by `(device, inode)` when available.
- Archives: `.zip`, `.tar`, `.7z` treated as opaque files.
- Default ignore globs (configurable):  
  `.git/`, `node_modules/`, `__pycache__/`, `.cache/`, `Thumbs.db`, `.DS_Store`.

---

## 7. Performance
- Multithreaded:
  - Workers default: `CPU cores`.
  - Cap: `min(32, 2×CPU cores)`.
- Memory-bounded queues for stat/read/hash tasks.
- Persistent cache to skip re-hashing and re-reading unchanged files.
- Internal data pipeline uses lightweight dataclasses for folder/group metadata while persisting fingerprints to disk, reducing Python object overhead and keeping REST schemas intact.
- Candidate pruning before similarity:
  - Bucket by `(total_bytes, file_count)` and quick sketches.
  - Optional future LSH (Locality-Sensitive Hashing) hook; not required for v1.

---

## 8. Change Safety
- Drift detection: if `size` or `mtime` changes during read, rescan once. If unstable again, skip file and mark folder `unstable=true`.
- Permission errors: skip with warning; include in reports.

---

## 9. Name Handling
- Respect underlying filesystem case rules by default.
- Option `force_case_insensitive=true`: lowercase both sides before compare.
- Normalize all names to NFC before any compare.

---

## 10. UI
- Web UI served from container on `:8080`.
- Views:
  1) **Duplicate groups**: `identical` folder groups.
  2) **Near-duplicate clusters**: folders with `sim ≥ 0.80`.
  3) **Overlap explorer**: select a folder to see where its bytes repeat.
- Sorting: by similarity, potential reclaimed bytes, path.
- Filtering: by label, similarity range, min total bytes, glob include/exclude.
- Item details:
  - Canonical folder shown once per group with aggregated byte size and file count.
  - Duplicate members list omits the canonical entry; each row is displayed relative to the active Root Path.
  - Pairwise similarity matrix.
  - Top K divergent files by delta bytes.
  - Stability and permission warnings.
- Progress telemetry:
  - Live counters for folders/files scanned, folders discovered, active workers.
  - Overall progress bar plus per-phase progress bars for `walking` (filesystem traversal), `aggregating` (hierarchy roll-up), and `grouping` (similarity computation), each with a status indicator and percentage.
  - Rolling ETA derived primarily from filesystem walk throughput, with phase information surfaced via `ScanProgress.phases`.
- Exports: current view → Markdown, JSON (JavaScript Object Notation), CSV (Comma-Separated Values).
- Internationalization: UTF-8 only for v1.
- Diff visualization:
  - REST endpoint `GET /api/scans/{scan_id}/groups/{group_id}/diff` returns a diff tree with `only_left`, `only_right`, and `mismatched` entries derived from aggregated fingerprints.
  - UI exposes a “Compare” action for near-duplicate members; modal renders side-by-side differences with byte sizes.
  - Folder Comparison panel shows canonical and duplicate folder contents, highlighting unique and mismatched entries; matching entries can be toggled on/off for clarity.

### 10.1 View Enhancements (Post-v2.1)
- **Tree View**: Similarity Groups now offer a List/Tree switch. The tree aggregates duplicate stats per folder (bytes, identical/near counts, reclaimable bytes) and supports search + expand/collapse for large hierarchies.
- **Progress Telemetry**: Scan progress panel streams phase (`walking`, `aggregating`, `grouping`), last processed path, and exposes per-phase progress and status.
- **Diff Workflow**: Compare modal integrates with the diff API so users can inspect folder-level differences before acting.
 - **Visual Insights**: Similarity Matrix (top-K adjacency) and Duplicate-density Treemap views are available for high-level exploration.

---

## 11. Deletion Workflow
- Requires RW mount and `deletion.enabled=true`.
- Two-step confirm:
  - Step 1: plan preview with reclaimed-bytes estimate.
  - Step 2: confirm token then apply.
- Quarantine when recycle not used:
  - Path: `<root>/.folderdupe_quarantine/YYYYMMDD/<absolute-path>`
  - Same filesystem as target to keep moves atomic.
  - Retention: 30 days. UI purge action empties quarantine.
- Recycle bins and snapshots:
  - If the host or NAS uses a recycle bin or snapshots, freed space may be delayed. UI shows both “bytes removed” and “bytes pending reclaim”.
- Safety:
  - Never delete outside the configured root.
  - Refuse deletion if paths escape root after symlink resolution.

---

## 12. Output Data and Schemas

### 12.1 Export header
```json
{
  "schema_version": 1,
  "generated_at": "ISO-8601 UTC",
  "root": "/data",
  "file_equality": "name_size|sha256",
  "min_similarity": 0.80,
  "structure_policy": "relative|bag_of_files",
  "filters": { "include": [], "exclude": [] }
}
```

### 12.2 Folder record
```json
{
  "path": "/data/photos/2019/trip",
  "total_bytes": 1234567890,
  "file_count": 4321,
  "unstable": false
}
```

### 12.3 Group record
```json
{
  "group_id": "g_000123",
  "label": "identical|near_duplicate",
  "canonical_path": "/data/photos/2019/trip",
  "members": [
    { "path": "/data/a", "total_bytes": 111, "file_count": 22 },
    { "path": "/data/b", "total_bytes": 111, "file_count": 22 }
  ],
  "pairwise_similarity": [
    { "a": 0, "b": 1, "similarity": 1.0 }
  ],
  "divergences": [
    { "path_a": "a/file.raw", "path_b": "b/file.raw", "delta_bytes": 1048576 }
  ],
  "suppressed_descendants": true
}
```

### 12.4 Warning record
```json
{
  "path": "/data/x",
  "type": "permission|unstable|io_error",
  "message": "string"
}
```

---

## 13. REST API (Application Programming Interface)
(omitted for brevity - included in final output)
