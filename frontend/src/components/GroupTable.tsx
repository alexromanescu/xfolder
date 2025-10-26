import type { GroupRecord } from "../api";
import { humanBytes } from "../format";

interface GroupTableProps {
  groups: GroupRecord[];
  selected: Set<string>;
  onToggle: (path: string) => void;
  emptyLabel: string;
}

const labelClass: Record<string, string> = {
  identical: "badge identical",
  near_duplicate: "badge near",
  partial_overlap: "badge partial",
};

export function GroupTable({ groups, selected, onToggle, emptyLabel }: GroupTableProps) {
  if (!groups.length) {
    return <p className="muted">{emptyLabel}</p>;
  }

  return (
    <div className="scroll-container">
      <table className="table">
        <thead>
          <tr>
            <th />
            <th>Group</th>
            <th>Members</th>
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
                  <div>{group.canonical_path}</div>
                  <div className="muted">{group.group_id}</div>
                </td>
                <td>
                  <div className="muted">Select paths to quarantine</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: 8 }}>
                    {group.members.map((member, index) => {
                      const memberPath = member.path;
                      const isCanonical = index === 0;
                      const checked = selected.has(memberPath);
                      return (
                        <label
                          key={memberPath}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "10px",
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={isCanonical}
                            onChange={() => onToggle(memberPath)}
                          />
                          <span>
                            {member.path}
                            <div className="muted">
                              {humanBytes(member.total_bytes)} • {member.file_count} files
                              {member.unstable ? " • unstable" : ""}
                            </div>
                          </span>
                        </label>
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
