export function humanBytes(value: number): string {
  if (value <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const scaled = value / Math.pow(1024, index);
  return `${scaled.toFixed(scaled >= 10 ? 0 : 1)} ${units[index]}`;
}

export function formatDate(value?: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

export function humanDuration(start?: string, end?: string): string {
  if (!start || !end) return "—";
  const delta = Math.max(0, new Date(end).getTime() - new Date(start).getTime());
  const seconds = Math.floor(delta / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  if (minutes < 60) return `${minutes}m ${rem}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function relativePath(path: string, root: string): string {
  if (!root) return path;
  const normalize = (value: string) => value.replace(/\/+$/, "");
  const normalizedRoot = normalize(root);
  const normalizedPath = normalize(path);
  if (!normalizedRoot) {
    return normalizedPath || ".";
  }
  if (normalizedPath === normalizedRoot) {
    return ".";
  }
  if (normalizedPath.startsWith(`${normalizedRoot}/`)) {
    const result = normalizedPath.slice(normalizedRoot.length + 1);
    return result || ".";
  }
  return path;
}

export function formatEta(seconds?: number | null): string {
  if (seconds == null) return "calculating";
  if (seconds <= 0) return "complete";
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))}s remaining`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.floor(seconds % 60);
  if (minutes < 60) return `${minutes}m ${rem}s remaining`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m remaining`;
}
