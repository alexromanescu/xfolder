import { useEffect, useMemo, useState } from "react";
import type { FolderLabel, GroupRecord } from "../api";
import { humanBytes, relativePath } from "../format";

type Node = {
  name: string;
  fullPath: string;
  children: Map<string, Node>;
  bytes: number;
  identical: number;
  near: number;
  reclaim: number;
  duplicateGroups: DuplicateGroup[];
};

type MemberSummary = {
  absolutePath: string;
  relativePath: string;
  totalBytes: number;
  fileCount: number;
  unstable: boolean;
  fullPath: string;
};

type DuplicateGroup = {
  groupId: string;
  label: FolderLabel;
  canonical: MemberSummary;
  duplicates: MemberSummary[];
};

interface TreeViewProps {
  rootPath: string;
  groups: GroupRecord[];
}

export function TreeView({ rootPath, groups }: TreeViewProps) {
  const treeData = useMemo(() => buildTree(rootPath, groups), [rootPath, groups]);
  const treeRoot = treeData.root;
  const lookup = treeData.lookup;
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(["/"]));
  const [query, setQuery] = useState("");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  useEffect(() => {
    if (selectedPath && !lookup.has(selectedPath)) {
      setSelectedPath(null);
    }
  }, [lookup, selectedPath]);

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
          onSelect={setSelectedPath}
          selectedPath={selectedPath}
        />
      </div>
      <TreeSelectionDetails node={selectedPath ? lookup.get(selectedPath) ?? null : null} lookup={lookup} />
    </div>
  );
}

function buildTree(
  rootPath: string,
  groups: GroupRecord[],
): { root: Node; lookup: Map<string, Node> } {
  const createNode = (name: string, fullPath: string): Node => ({
    name,
    fullPath,
    children: new Map(),
    bytes: 0,
    identical: 0,
    near: 0,
    reclaim: 0,
    duplicateGroups: [],
  });
  const root: Node = createNode(".", "/");
  const lookup = new Map<string, Node>([[root.fullPath, root]]);

  const toRel = (abs: string) => relativePath(abs, rootPath);

  function ensure(path: string): Node {
    const normalized = path === "." ? "/" : path.startsWith("/") ? path : `/${path}`;
    if (lookup.has(normalized)) {
      return lookup.get(normalized)!;
    }
    const parts = normalized === "/" ? [] : normalized.slice(1).split("/").filter(Boolean);
    let cur = root;
    let currentFull = "/";
    for (const part of parts) {
      const nextFull = currentFull === "/" ? `/${part}` : `${currentFull}/${part}`;
      if (!cur.children.has(part)) {
        const node = createNode(part, nextFull);
        cur.children.set(part, node);
        lookup.set(nextFull, node);
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
    const canonicalRel = toRel(String(canonical.path));
    const canonicalNode = ensure(canonicalRel);
    canonicalNode.bytes = Math.max(canonicalNode.bytes, canonical.total_bytes);
    if (group.label === "identical") canonicalNode.identical += members.length - 1;
    else canonicalNode.near += members.length - 1;
    let reclaim = 0;
    for (const m of members.slice(1)) reclaim += m.total_bytes;
    canonicalNode.reclaim += reclaim;

    const canonicalSummary = summarizeMember(canonical, canonicalNode.fullPath, canonicalRel);
    const duplicateSummaries: MemberSummary[] = [];
    for (const m of members.slice(1)) {
      const rel = toRel(String(m.path));
      const node = ensure(rel);
      node.bytes = Math.max(node.bytes, m.total_bytes);
      if (group.label === "identical") node.identical += 1;
      else node.near += 1;
      duplicateSummaries.push(summarizeMember(m, node.fullPath, rel));
    }
    if (duplicateSummaries.length) {
      canonicalNode.duplicateGroups.push({
        groupId: group.group_id,
        label: group.label,
        canonical: canonicalSummary,
        duplicates: duplicateSummaries,
      });
    }
  }

  return { root, lookup };
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
  onSelect,
  selectedPath,
}: {
  node: Node;
  level: number;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  filter: string;
  onSelect: (path: string) => void;
  selectedPath: string | null;
}) {
  const hasChildren = node.children.size > 0;
  const isOpen = expanded.has(node.fullPath);
  const isSelected = selectedPath === node.fullPath;

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
      <div
        className={`tree-row${isSelected ? " selected" : ""}`}
        style={{ paddingLeft: level * 18 }}
        onClick={() => onSelect(node.fullPath)}
      >
        {hasChildren ? (
          <button
            className="tree-toggle"
            onClick={(event) => {
              event.stopPropagation();
              onToggle(node.fullPath);
            }}
            aria-label={isOpen ? "Collapse" : "Expand"}
          >
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
      {node.duplicateGroups.length ? (
        <div className="tree-duplicates" style={{ marginLeft: level * 18 + 24 }}>
          {node.duplicateGroups.map((group) => (
            <div key={group.groupId}>
              <div className="muted">
                Group {group.groupId} · {group.label === "identical" ? "Identical" : "Near duplicate"}
              </div>
              <div className="duplicates-list">
                {group.duplicates.map((dup) => (
                  <div className="duplicate-row" key={`${group.groupId}-${dup.fullPath}`}>
                    <div>
                      {dup.relativePath}
                      <div className="muted">
                        {humanBytes(dup.totalBytes)} • {dup.fileCount} files
                        {dup.unstable ? " • unstable" : ""}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
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
              onSelect={onSelect}
              selectedPath={selectedPath}
            />
          ))
      ) : null}
    </div>
  );
}

function TreeSelectionDetails({ node, lookup }: { node: Node | null; lookup: Map<string, Node> }) {
  if (!node) {
    return (
      <div className="tree-selection-panel">
        <p className="muted">Select a branch to compare duplicates.</p>
      </div>
    );
  }
  const readable = node.fullPath === "/" ? "." : node.fullPath.slice(1);

  return (
    <div className="tree-selection-panel">
      <div className="panel-title">Branch comparison</div>
      <p className="muted">Selected: {readable}</p>
      {node.duplicateGroups.length ? (
        node.duplicateGroups.map((group) => (
          <div className="branch-section" key={group.groupId}>
            <div className="branch-header">
              <strong>{group.label === "identical" ? "Identical group" : "Near duplicate group"}</strong>
              <span className="muted">Group {group.groupId}</span>
            </div>
            <div className="branch-grid">
              <SubtreeCard title="Original" note={group.canonical.relativePath} node={lookup.get(group.canonical.fullPath)} />
              {group.duplicates.map((dup) => (
                <SubtreeCard
                  key={`${group.groupId}-${dup.fullPath}`}
                  title="Duplicate"
                  note={dup.relativePath}
                  node={lookup.get(dup.fullPath)}
                />
              ))}
            </div>
          </div>
        ))
      ) : (
        <p className="muted">No duplicates tracked for this branch yet.</p>
      )}
    </div>
  );
}

function SubtreeCard({ title, note, node }: { title: string; note: string; node: Node | undefined }) {
  if (!node) {
    return (
      <div className="subtree-card">
        <div className="subtree-title">{title}</div>
        <p className="muted">Folder data unavailable.</p>
      </div>
    );
  }
  return (
    <div className="subtree-card">
      <div className="subtree-title">{title}</div>
      <div className="muted">{note || "."}</div>
      <div className="subtree-list">
        <StaticBranch node={node} base={node.fullPath} depth={0} />
      </div>
    </div>
  );
}

const MAX_BRANCH_DEPTH = 4;

function StaticBranch({ node, base, depth }: { node: Node; base: string; depth: number }) {
  const relativeName = toRelativeName(node.fullPath, base);
  const children = Array.from(node.children.values()).sort((a, b) => a.name.localeCompare(b.name));
  return (
    <div className="subtree-node">
      <div className="subtree-row" style={{ paddingLeft: depth * 16 }}>
        <span>{relativeName}</span>
        <span>{humanBytes(node.bytes)}</span>
      </div>
      {depth < MAX_BRANCH_DEPTH && children.length ? (
        children.map((child) => <StaticBranch key={child.fullPath} node={child} base={base} depth={depth + 1} />)
      ) : null}
      {depth === MAX_BRANCH_DEPTH && children.length ? <div className="muted subtree-row" style={{ paddingLeft: (depth + 1) * 16 }}>…</div> : null}
    </div>
  );
}

function summarizeMember(
  record: GroupRecord["members"][number],
  fullPath: string,
  relative: string,
): MemberSummary {
  return {
    absolutePath: String(record.path),
    relativePath: relative,
    totalBytes: record.total_bytes,
    fileCount: record.file_count,
    unstable: record.unstable,
    fullPath,
  };
}

function toRelativeName(fullPath: string, base: string): string {
  if (fullPath === base) return ".";
  const prefix = base === "/" ? "/" : `${base}/`;
  if (fullPath.startsWith(prefix)) {
    return fullPath.slice(prefix.length) || ".";
  }
  return fullPath === "/" ? "." : fullPath.slice(1);
}
