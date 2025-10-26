interface MetricCardProps {
  title: string;
  value: string;
  hint?: string;
}

export function MetricCard({ title, value, hint }: MetricCardProps) {
  return (
    <div className="card">
      <div className="card-title">{title}</div>
      <div className="card-value">
        <strong>{value}</strong>
        {hint ? <span>{hint}</span> : null}
      </div>
    </div>
  );
}
