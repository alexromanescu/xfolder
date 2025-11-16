import type { TreemapNode } from "../api";
import { humanBytes } from "../format";

interface Props {
  tree: TreemapNode | null;
  loading?: boolean;
}

export function DensityTreemap({ tree, loading }: Props) {
  if (loading) {
    return <p className="muted">Loading treemap…</p>;
  }
  if (!tree) {
    return <p className="muted">Treemap data unavailable. Run a scan or refresh once it completes.</p>;
  }

  const maxDuplicate = Math.max(tree.duplicate_bytes, 1);
  return (
    <div className="treemap">
      <TreemapBranch node={tree} depth={0} maxDuplicate={maxDuplicate} />
    </div>
  );
}

interface BranchProps {
  node: TreemapNode;
  depth: number;
  maxDuplicate: number;
}

function TreemapBranch({ node, depth, maxDuplicate }: BranchProps) {
  const width = Math.max(2, Math.round((node.duplicate_bytes / maxDuplicate) * 100));
  return (
    <div className="treemap-node" style={{ marginLeft: depth * 12 }}>
      <div className="treemap-bar">
        <div className="treemap-bar-fill" style={{ width: `${width}%`, opacity: Math.min(1, node.duplicate_bytes / maxDuplicate + 0.1) }} />
        <div className="treemap-label">
          <strong>{node.name || node.path || "root"}</strong>
          <span>{humanBytes(node.total_bytes)}</span>
          <span>Dup: {humanBytes(node.duplicate_bytes)}</span>
          <span>
            {node.identical_groups} identical · {node.near_groups} near
          </span>
        </div>
      </div>
      {node.children?.length ? (
        <div className="treemap-children">
          {node.children.slice(0, 25).map((child) => (
            <TreemapBranch key={child.path} node={child} depth={depth + 1} maxDuplicate={maxDuplicate} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
