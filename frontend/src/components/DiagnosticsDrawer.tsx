import { useEffect, useState } from "react";
import type { LogEntry } from "../api";
import { formatDate } from "../format";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function DiagnosticsDrawer({ open, onClose }: Props) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    setError(null);
    const source = new EventSource("/api/system/logs/stream");
    source.onmessage = (event) => {
      const payload = JSON.parse(event.data) as LogEntry;
      if (cancelled) return;
      setEntries((prev) => {
        const next = [...prev, payload];
        if (next.length > 200) {
          next.shift();
        }
        return next;
      });
    };
    source.onerror = () => {
      if (cancelled) return;
      setError("Live log stream unavailable. Confirm log streaming is enabled server-side.");
      source.close();
    };
    return () => {
      cancelled = true;
      source.close();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="drawer" onClick={onClose}>
      <div className="drawer-panel" onClick={(event) => event.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <div className="panel-title">Diagnostics</div>
            <p className="muted">Live server logs for stuck-scan debugging.</p>
          </div>
          <button className="button secondary" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        {error ? <p className="muted">{error}</p> : null}
        <div className="log-list">
          {entries.map((entry, index) => (
            <div key={`${entry.timestamp}-${index}`} className={`log-entry level-${entry.level}`}>
              <div className="log-meta">
                <span>{formatDate(entry.timestamp)}</span>
                <span>{entry.level.toUpperCase()}</span>
                <span>{entry.logger}</span>
              </div>
              <div>{entry.message}</div>
            </div>
          ))}
          {!entries.length && !error ? <p className="muted">Waiting for log events…</p> : null}
        </div>
      </div>
    </div>
  );
}
