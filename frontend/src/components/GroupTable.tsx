import type { GroupRecord } from "../api";
import { humanBytes, relativePath } from "../format";

interface GroupTableProps {
  groups: GroupRecord[];
  rootPath: string;
  selected: Set<string>;
  onToggle: (path: string) => void;
  emptyLabel: string;
  onCompare: (group: GroupRecord, member: string) => void;
}

const labelClass: Record<string, string> = {
  identical: "badge identical",
  near_duplicate: "badge near",
  partial_overlap: "badge partial",
};

export function GroupTable({
  groups,
  rootPath,
  selected,
  onToggle,
  emptyLabel,
  onCompare,
}: GroupTableProps) {
  if (!groups.length) {
    return <p className="muted">{emptyLabel}</p>;
  }

  return (
    <div className="scroll-container">
      <table className="table">
        <thead>
          <tr>
            <th />
            <th>Folder</th>
            <th>Duplicates</th>
            <th>Similarity</th>
            <th>Reclaimable</th>
            <th>Stability</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const maxSimilarity = group.pairwise_similarity.reduce(
              (max, pair) => Math.max(max, pair.similarity),
              0,
            );
            const reclaimable =
              group.members.length > 1
                ? group.members
                    .slice(1)
                    .reduce((sum, member) => sum + member.total_bytes, 0)
                : 0;
            const reference = group.members[0];
            const referencePath = reference ? relativePath(reference.path, rootPath) : group.canonical_path;
            const isNearDuplicate = maxSimilarity < 1 - 1e-9;
            return (
              <tr key={group.group_id}>
                <td>
                  <span className={labelClass[group.label]}>
                    {group.label === "identical"
                      ? "Identical"
                      : group.label === "near_duplicate"
                        ? "Near Duplicate"
                      : "Overlap"}
                  </span>
                </td>
                <td>
                  <div>{referencePath}</div>
                  {reference ? (
                    <div className="muted">
                      {humanBytes(reference.total_bytes)} • {reference.file_count} files
                    </div>
                  ) : null}
                  <div className="muted">{group.group_id}</div>
                </td>
                <td>
                  <div className="muted">Select paths to quarantine</div>
                  <div className="duplicates-list">
                    {group.members.slice(1).map((member) => {
                      const memberPath = member.path;
                      const checked = selected.has(memberPath);
                      return (
                        <div className="duplicate-row" key={memberPath}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => onToggle(memberPath)}
                          />
                          <div>
                            {relativePath(member.path, rootPath)}
                            <div className="muted">
                              {humanBytes(member.total_bytes)} • {member.file_count} files
                              {member.unstable ? " • unstable" : ""}
                            </div>
                          </div>
                          {isNearDuplicate ? (
                            <button
                              type="button"
                              className="button secondary compare-button"
                              onClick={() => onCompare(group, member.relative_path)}
                            >
                              Compare
                            </button>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </td>
                <td>
                  <div>{(maxSimilarity * 100).toFixed(1)}%</div>
                  {group.divergences.length ? (
                    <div className="muted">
                      Top delta: {humanBytes(group.divergences[0].delta_bytes)}
                    </div>
                  ) : null}
                </td>
                <td>{reclaimable ? humanBytes(reclaimable) : "—"}</td>
                <td>
                  {group.members.some((member) => member.unstable) ? (
                    <span className="pill">Changes detected</span>
                  ) : (
                    <span className="muted">Stable</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
