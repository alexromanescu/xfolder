import type { GroupRecord } from "../api";
import { humanBytes, relativePath } from "../format";

interface GroupTableProps {
  groups: GroupRecord[];
  rootPath: string;
  selected: Set<string>;
  onToggle: (path: string) => void;
  emptyLabel: string;
  onCompare: (group: GroupRecord, member: string) => void;
  onSelectGroup?: (group: GroupRecord) => void;
  selectedGroupId?: string | null;
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
  onSelectGroup,
  selectedGroupId,
}: GroupTableProps) {
  if (!groups.length) {
    return <p className="muted">{emptyLabel}</p>;
  }

  return (
    <div className="scroll-container">
      <table className="table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Folder</th>
            <th>Members</th>
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
            const isSelected = group.group_id === selectedGroupId;
            const duplicateCount = Math.max(0, group.members.length - 1);
            return (
              <tr key={group.group_id} className={isSelected ? "selected" : ""}>
                <td>
                  <div className="group-summary">
                    <span className={labelClass[group.label]}>
                      {group.label === "identical"
                        ? "Identical"
                        : group.label === "near_duplicate"
                          ? "Near Duplicate"
                          : "Overlap"}
                    </span>
                    <div className="muted summary-line">{(maxSimilarity * 100).toFixed(1)}%</div>
                    <div className="muted summary-line">
                      {reclaimable ? humanBytes(reclaimable) : "—"}
                    </div>
                    <div className="muted summary-line">
                      {group.members.some((member) => member.unstable) ? "Changes detected" : "Stable"}
                    </div>
                  </div>
                </td>
                <td className="folder-cell">
                  <div className="folder-path">{referencePath}</div>
                  {reference ? (
                    <div className="muted">
                      {humanBytes(reference.total_bytes)} • {reference.file_count} files
                    </div>
                  ) : null}
                  <div className="muted">{group.group_id}</div>
                </td>
                <td>
                  {onSelectGroup && group.members.length > 1 ? (
                    <button
                      type="button"
                      className="button secondary compare-button"
                      style={{ marginTop: 6 }}
                      onClick={() => onSelectGroup(group)}
                    >
                      View comparison
                    </button>
                    ) : null}
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
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
