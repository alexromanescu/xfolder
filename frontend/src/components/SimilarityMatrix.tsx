import type { SimilarityMatrixEntry } from "../api";
import { humanBytes } from "../format";

interface Props {
  entries: SimilarityMatrixEntry[];
  loading?: boolean;
}

export function SimilarityMatrixView({ entries, loading }: Props) {
  if (loading) {
    return <p className="muted">Loading similarity matrix…</p>;
  }
  if (!entries.length) {
    return <p className="muted">No duplicate adjacencies available for this scan yet.</p>;
  }
  return (
    <div className="matrix-grid">
      {entries.map((entry) => {
        const key = `${entry.group_id}-${entry.left.relative_path}-${entry.right.relative_path}`;
        const intensity = Math.round(entry.similarity * 100);
        const gradient = `linear-gradient(90deg, var(--primary-soft) ${intensity}%, var(--muted-surface) ${intensity}%)`;
        return (
          <div key={key} className="matrix-entry">
            <div className="matrix-swatch" style={{ background: gradient }} />
            <div className="matrix-content">
              <div className="matrix-paths">
                <strong>{entry.left.relative_path}</strong>
                <span>↔</span>
                <strong>{entry.right.relative_path}</strong>
              </div>
              <div className="matrix-meta">
                <span>{(entry.similarity * 100).toFixed(1)}% similar</span>
                <span>Group {entry.group_id}</span>
                <span>Bytes: {humanBytes(entry.combined_bytes)}</span>
                <span>Reclaimable ≈ {humanBytes(entry.reclaimable_bytes)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
