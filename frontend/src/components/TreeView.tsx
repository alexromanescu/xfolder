import { useMemo, useState } from "react";
import type { GroupRecord } from "../api";
import { humanBytes, relativePath } from "../format";

type Node = {
  name: string;
  fullPath: string;
  children: Map<string, Node>;
  bytes: number;
  identical: number;
  near: number;
  reclaim: number;
};

interface TreeViewProps {
  rootPath: string;
  groups: GroupRecord[];
}

export function TreeView({ rootPath, groups }: TreeViewProps) {
  const treeRoot = useMemo(() => buildTree(rootPath, groups), [rootPath, groups]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(["/"]));
  const [query, setQuery] = useState("");

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="tree-view">
      <div className="tree-controls">
        <input
          placeholder="Filter paths…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="button secondary" type="button" onClick={() => setExpanded(new Set(["/"]))}>
          Collapse all
        </button>
        <button className="button secondary" type="button" onClick={() => setExpanded(expandAll(treeRoot))}>
          Expand all
        </button>
      </div>
      <div className="tree-container">
        <TreeNode
          node={treeRoot}
          level={0}
          expanded={expanded}
          onToggle={toggle}
          filter={query.trim()}
        />
      </div>
    </div>
  );
}

function buildTree(rootPath: string, groups: GroupRecord[]): Node {
  const root: Node = { name: ".", fullPath: "/", children: new Map(), bytes: 0, identical: 0, near: 0, reclaim: 0 };

  const toRel = (abs: string) => relativePath(abs, rootPath);

  function ensure(path: string): Node {
    const parts = path.split("/").filter(Boolean);
    let cur = root;
    let currentFull = "/";
    for (const part of parts) {
      const nextFull = currentFull === "/" ? `/${part}` : `${currentFull}/${part}`;
      if (!cur.children.has(part)) {
        cur.children.set(part, { name: part, fullPath: nextFull, children: new Map(), bytes: 0, identical: 0, near: 0, reclaim: 0 });
      }
      cur = cur.children.get(part)!;
      currentFull = nextFull;
    }
    return cur;
  }

  for (const group of groups) {
    const members = group.members;
    if (!members?.length) continue;
    const canonical = members[0];
    const canonicalNode = ensure(toRel(String(canonical.path)));
    canonicalNode.bytes = Math.max(canonicalNode.bytes, canonical.total_bytes);
    if (group.label === "identical") canonicalNode.identical += members.length - 1;
    else canonicalNode.near += members.length - 1;
    let reclaim = 0;
    for (const m of members.slice(1)) reclaim += m.total_bytes;
    canonicalNode.reclaim += reclaim;

    for (const m of members.slice(1)) {
      const node = ensure(toRel(String(m.path)));
      node.bytes = Math.max(node.bytes, m.total_bytes);
      if (group.label === "identical") node.identical += 1;
      else node.near += 1;
    }
  }

  return root;
}

function expandAll(node: Node): Set<string> {
  const result = new Set<string>();
  const walk = (n: Node) => {
    result.add(n.fullPath);
    for (const child of n.children.values()) walk(child);
  };
  walk(node);
  return result;
}

function TreeNode({
  node,
  level,
  expanded,
  onToggle,
  filter,
}: {
  node: Node;
  level: number;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  filter: string;
}) {
  const hasChildren = node.children.size > 0;
  const isOpen = expanded.has(node.fullPath);

  const matches = (value: string) => value.toLowerCase().includes(filter.toLowerCase());
  const matchesFilter = (current: Node): boolean => {
    if (!filter) return true;
    if (matches(current.fullPath) || matches(current.name)) return true;
    for (const child of current.children.values()) {
      if (matchesFilter(child)) return true;
    }
    return false;
  };
  if (!matchesFilter(node)) return null;

  return (
    <div>
      <div className="tree-row" style={{ paddingLeft: level * 18 }}>
        {hasChildren ? (
          <button className="tree-toggle" onClick={() => onToggle(node.fullPath)} aria-label={isOpen ? "Collapse" : "Expand"}>
            {isOpen ? "▾" : "▸"}
          </button>
        ) : (
          <span className="tree-spacer" />
        )}
        <span className="tree-path">{node.fullPath === "/" ? "." : node.fullPath.slice(1)}</span>
        <span className="tree-metrics">{humanBytes(node.bytes)}</span>
        <span className="tree-badges">
          {node.identical > 0 ? <span className="badge identical">={node.identical}</span> : null}
          {node.near > 0 ? <span className="badge near">~{node.near}</span> : null}
          {node.reclaim > 0 ? <span className="pill">{humanBytes(node.reclaim)} reclaim</span> : null}
        </span>
      </div>
      {isOpen && hasChildren ? (
        Array.from(node.children.values())
          .sort((a, b) => a.name.localeCompare(b.name))
          .map((child) => (
            <TreeNode
              key={child.fullPath}
              node={child}
              level={level + 1}
              expanded={expanded}
              onToggle={onToggle}
              filter={filter}
            />
          ))
      ) : null}
    </div>
  );
}
