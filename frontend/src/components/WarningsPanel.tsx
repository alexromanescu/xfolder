import type { WarningRecord } from "../api";

interface WarningsPanelProps {
  warnings: WarningRecord[];
}

export function WarningsPanel({ warnings }: WarningsPanelProps) {
  if (!warnings.length) {
    return (
      <div className="panel">
        <div className="panel-title">Warnings</div>
        <p className="muted">The last scan completed without reported warnings.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-title">Warnings</div>
      <div className="warning-list">
        {warnings.map((warning, index) => (
          <div key={`${warning.path}-${index}`} className="warning-item">
            <strong>{warning.type.toUpperCase()}</strong>
            <div>{warning.message}</div>
            <div className="muted">{warning.path}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
