import type { GroupDiff } from "../api";
import { humanBytes } from "../format";

interface DiffModalProps {
  open: boolean;
  diff?: GroupDiff;
  loading: boolean;
  onClose: () => void;
}

export function DiffModal({ open, diff, loading, onClose }: DiffModalProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal-panel">
        <div className="modal-header">
          <h2 style={{ margin: 0 }}>Compare Differences</h2>
          <button type="button" className="button secondary" onClick={onClose}>
            Close
          </button>
        </div>
        {loading ? (
          <p className="muted">Loading diff…</p>
        ) : diff ? (
          <div className="modal-columns">
            <DiffColumn
              title={`Only in ${diff.left.relative_path === "." ? diff.left.path : diff.left.relative_path}`}
              entries={diff.only_left}
              emptyMessage="No unique items"
            />
            <DiffColumn
              title={`Only in ${diff.right.relative_path === "." ? diff.right.path : diff.right.relative_path}`}
              entries={diff.only_right}
              emptyMessage="No unique items"
            />
            <MismatchColumn entries={diff.mismatched} />
          </div>
        ) : (
          <p className="muted">No diff data available.</p>
        )}
      </div>
    </div>
  );
}

function DiffColumn({
  title,
  entries,
  emptyMessage,
}: {
  title: string;
  entries: { path: string; bytes: number }[];
  emptyMessage: string;
}) {
  return (
    <div className="diff-list">
      <strong>{title}</strong>
      {entries.length ? (
        entries.map((entry) => (
          <div key={entry.path}>
            {entry.path || "(root)"}
            <div className="muted">{humanBytes(entry.bytes)}</div>
          </div>
        ))
      ) : (
        <span className="muted">{emptyMessage}</span>
      )}
    </div>
  );
}

function MismatchColumn({
  entries,
}: {
  entries: { path: string; left_bytes: number; right_bytes: number }[];
}) {
  return (
    <div className="diff-list">
      <strong>Mismatched files</strong>
      {entries.length ? (
        entries.map((entry) => (
          <div key={entry.path}>
            {entry.path}
            <div className="muted">
              Left: {humanBytes(entry.left_bytes)} · Right: {humanBytes(entry.right_bytes)}
            </div>
          </div>
        ))
      ) : (
        <span className="muted">No mismatches</span>
      )}
    </div>
  );
}
