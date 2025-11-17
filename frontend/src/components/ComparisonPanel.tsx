import type { GroupContents, GroupDiff, GroupRecord, MemberContents, FolderEntry } from "../api";
import { humanBytes } from "../format";

export interface ComparisonEntry {
  member: GroupRecord["members"][number];
  diff?: GroupDiff;
  error?: string;
}

interface ComparisonPanelProps {
  group: GroupRecord | null;
  entries: ComparisonEntry[];
  loading: boolean;
  contents: GroupContents | null;
  showMatches: boolean;
  onToggleShowMatches: () => void;
  onClear: () => void;
}

export function ComparisonPanel({ group, entries, loading, contents, showMatches, onToggleShowMatches, onClear }: ComparisonPanelProps) {
  if (!group) {
    return (
      <div className="panel comparison-panel">
        <div className="panel-title">Folder Comparison</div>
        <p className="muted">Select a canonical folder from the list or tree to inspect its duplicates.</p>
      </div>
    );
  }

  const canonical = group.members[0];
  const duplicates = group.members.slice(1);
  const entryLookup = new Map(entries.map((entry) => [entry.member.relative_path, entry]));
  const canonicalEntries = contents?.canonical.entries ?? [];
  const duplicateEntries = new Map<string, MemberContents>(
    (contents?.duplicates ?? []).map((dup) => [dup.relative_path, dup]),
  );
  const canonicalSummary = buildCanonicalSummary(entries);

  return (
    <div className="comparison-panel">
      <div className="panel-header">
        <div>
          <div className="panel-title">Folder Comparison</div>
          <p className="muted">
            Group {group.group_id} · {group.label === "identical" ? "Identical" : "Near duplicate"}
          </p>
        </div>
        <button className="button secondary" type="button" onClick={onClear}>
          Clear selection
        </button>
      </div>
      <div className="comparison-panel-inner">
        {duplicates.length === 0 ? (
          <p className="muted">This folder does not have duplicates to compare.</p>
        ) : (
          <>
            <div className="comparison-toolbar">
              <label>
                <input type="checkbox" checked={showMatches} onChange={onToggleShowMatches} /> Show matching files
              </label>
            </div>
            <div className="comparison-grid">
              <div className="comparison-card canonical">
                <div className="comparison-card-title">Canonical</div>
                <FolderSummary relativePath={canonical.relative_path} totalBytes={canonical.total_bytes} fileCount={canonical.file_count} />
                <FolderContent
                  variant="canonical"
                  onlyEntries={canonicalSummary.only}
                  changedEntries={canonicalSummary.changed}
                  allEntries={canonicalEntries}
                  showMatches={showMatches}
                  loading={loading}
                />
              </div>
              {duplicates.map((member) => {
                const entry = entryLookup.get(member.relative_path);
                const memberEntries = duplicateEntries.get(member.relative_path)?.entries ?? [];
                return (
                  <div className="comparison-card" key={member.relative_path}>
                    <div className="comparison-card-title">Duplicate</div>
                    <FolderSummary
                      relativePath={member.relative_path}
                      totalBytes={member.total_bytes}
                      fileCount={member.file_count}
                      unstable={member.unstable}
                    />
                    <FolderContent
                      variant="duplicate"
                      diff={entry?.diff}
                      error={entry?.error}
                      allEntries={memberEntries}
                      showMatches={showMatches}
                      loading={loading}
                    />
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function FolderSummary({
  relativePath,
  totalBytes,
  fileCount,
  unstable,
}: {
  relativePath: string;
  totalBytes: number;
  fileCount: number;
  unstable?: boolean;
}) {
  return (
    <div>
      <div className="comparison-path">{relativePath || "."}</div>
      <div className="muted">
        {humanBytes(totalBytes)} • {fileCount} files
        {unstable ? " • unstable" : ""}
      </div>
    </div>
  );
}

function DiffOverview({ diff }: { diff: GroupDiff }) {
  const hasChanges =
    diff.only_left.length > 0 || diff.only_right.length > 0 || diff.mismatched.length > 0;
  if (!hasChanges) {
    return <p className="muted">Folders match exactly.</p>;
  }
  return (
    <div className="diff-grid">
      {diff.only_left.length ? (
        <DiffList title="Only in canonical" entries={diff.only_left.map((entry) => ({ label: entry.path, bytes: entry.bytes }))} variant="removed" />
      ) : null}
      {diff.only_right.length ? (
        <DiffList title="Only in duplicate" entries={diff.only_right.map((entry) => ({ label: entry.path, bytes: entry.bytes }))} variant="added" />
      ) : null}
      {diff.mismatched.length ? (
        <DiffList
          title="Size differences"
          entries={diff.mismatched.map((entry) => ({
            label: entry.path,
            bytes: Math.abs(entry.left_bytes - entry.right_bytes),
          }))}
          variant="changed"
        />
      ) : null}
    </div>
  );
}

function DiffList({
  title,
  entries,
  variant,
}: {
  title: string;
  entries: { label: string; bytes: number }[];
  variant: "added" | "removed" | "changed";
}) {
  return (
    <div className={`diff-column ${variant}`}>
      <div className="diff-column-title">{title}</div>
      <ul>
        {entries.slice(0, 6).map((entry) => (
          <li key={`${variant}-${entry.label}`}>
            <span>{entry.label}</span>
            <strong>{humanBytes(entry.bytes)}</strong>
          </li>
        ))}
        {entries.length > 6 ? <li className="muted">+{entries.length - 6} more…</li> : null}
      </ul>
    </div>
  );
}

function FolderContent({
  variant,
  onlyEntries,
  changedEntries,
  diff,
  error,
  allEntries,
  showMatches,
  loading,
}: {
  variant: "canonical" | "duplicate";
  onlyEntries?: { label: string; bytes: number }[];
  changedEntries?: { label: string; bytes: number }[];
  diff?: GroupDiff;
  error?: string;
  allEntries?: FolderEntry[];
  showMatches: boolean;
  loading: boolean;
}) {
  if (loading) return <p className="muted">Loading differences…</p>;
  if (error) return <p className="muted">Unable to load diff — {error}</p>;
  const entries = allEntries ?? [];
  if (variant === "canonical") {
    const removedSet = new Set((onlyEntries ?? []).map((entry) => entry.label));
    const changedSet = new Set((changedEntries ?? []).map((entry) => entry.label));
    return <EntriesTable entries={entries} removed={removedSet} changed={changedSet} showMatches={showMatches} emptyLabel="No files recorded." />;
  }
  if (!diff) {
    return <EntriesTable entries={entries} showMatches={showMatches} emptyLabel="No files recorded." />;
  }
  const addedSet = new Set(diff.only_right.map((entry) => entry.path));
  const changedSet = new Set(diff.mismatched.map((entry) => entry.path));
  return (
    <EntriesTable
      entries={entries}
      added={addedSet}
      changed={changedSet}
      showMatches={showMatches}
      emptyLabel="Matches canonical structure"
    />
  );
}

function buildCanonicalSummary(entries: ComparisonEntry[]) {
  const onlyMap = new Map<string, number>();
  const changedMap = new Map<string, number>();
  for (const entry of entries) {
    entry.diff?.only_left.forEach((item) => {
      onlyMap.set(item.path, (onlyMap.get(item.path) ?? 0) + item.bytes);
    });
    entry.diff?.mismatched.forEach((item) => {
      const delta = Math.abs(item.left_bytes - item.right_bytes);
      changedMap.set(item.path, Math.max(changedMap.get(item.path) ?? 0, delta));
    });
  }
  return {
    only: Array.from(onlyMap.entries()).map(([label, bytes]) => ({ label, bytes })),
    changed: Array.from(changedMap.entries()).map(([label, bytes]) => ({ label, bytes })),
  };
}

function EntriesTable({
  entries,
  added,
  removed,
  changed,
  showMatches,
  emptyLabel,
}: {
  entries: FolderEntry[];
  added?: Set<string>;
  removed?: Set<string>;
  changed?: Set<string>;
  showMatches: boolean;
  emptyLabel: string;
}) {
  if (!entries.length) {
    return <p className="muted">{emptyLabel}</p>;
  }
  const rows = entries.map((entry) => {
    const path = entry.path;
    const status = added?.has(path)
      ? "added"
      : removed?.has(path)
        ? "removed"
        : changed?.has(path)
          ? "changed"
          : "match";
    if (!showMatches && status === "match") {
      return null;
    }
    return (
      <li key={path} className={`entry-row status-${status}`}>
        <span>{path}</span>
        <span>{humanBytes(entry.bytes)}</span>
      </li>
    );
  });
  const visibleRows = rows.filter(Boolean);
  if (!visibleRows.length) {
    return <p className="muted">{showMatches ? emptyLabel : "No differences to display."}</p>;
  }
  return <ul className="entries-table">{visibleRows}</ul>;
}
