import { useMemo, useState } from "react";
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
  group?: GroupRecord;
};

type MemberSummary = {
  relativePath: string;
  totalBytes: number;
  fileCount: number;
  unstable: boolean;
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
  onSelectGroup?: (group: GroupRecord) => void;
  selectedGroupId?: string | null;
}

export function TreeView({ rootPath, groups, onSelectGroup, selectedGroupId }: TreeViewProps) {
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
          onSelectGroup={onSelectGroup}
          selectedGroupId={selectedGroupId}
        />
      </div>
    </div>
  );
}

function buildTree(rootPath: string, groups: GroupRecord[]): Node {
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

  const toRel = (abs: string) => relativePath(abs, rootPath);

  function ensure(path: string): Node {
    const normalized = path === "." ? "/" : path.startsWith("/") ? path : `/${path}`;
    const parts = normalized === "/" ? [] : normalized.slice(1).split("/").filter(Boolean);
    let cur = root;
    let currentFull = "/";
    for (const part of parts) {
      const nextFull = currentFull === "/" ? `/${part}` : `${currentFull}/${part}`;
      if (!cur.children.has(part)) {
        cur.children.set(part, createNode(part, nextFull));
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
    canonicalNode.group = group;
    canonicalNode.bytes = Math.max(canonicalNode.bytes, canonical.total_bytes);
    if (group.label === "identical") canonicalNode.identical += members.length - 1;
    else canonicalNode.near += members.length - 1;
    let reclaim = 0;
    for (const m of members.slice(1)) reclaim += m.total_bytes;
    canonicalNode.reclaim += reclaim;

    const canonicalSummary = summarizeMember(canonical, canonicalRel);
    const duplicateSummaries: MemberSummary[] = members.slice(1).map((member) => summarizeMember(member, toRel(String(member.path))));
    if (duplicateSummaries.length) {
      canonicalNode.duplicateGroups.push({
        groupId: group.group_id,
        label: group.label,
        canonical: canonicalSummary,
        duplicates: duplicateSummaries,
      });
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
  onSelectGroup,
  selectedGroupId,
}: {
  node: Node;
  level: number;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  filter: string;
  onSelectGroup?: (group: GroupRecord) => void;
  selectedGroupId?: string | null;
}) {
  const hasChildren = node.children.size > 0;
  const isOpen = expanded.has(node.fullPath);
  const isSelected = node.group ? node.group.group_id === selectedGroupId : false;

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
        onClick={() => {
          if (node.group && onSelectGroup) onSelectGroup(node.group);
        }}
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
                {group.duplicates.map((dup, index) => (
                  <div className="duplicate-row" key={`${group.groupId}-${index}`}>
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
              onSelectGroup={onSelectGroup}
              selectedGroupId={selectedGroupId}
            />
          ))
      ) : null}
    </div>
  );
}

function summarizeMember(record: GroupRecord["members"][number], relative: string): MemberSummary {
  return {
    relativePath: relative,
    totalBytes: record.total_bytes,
    fileCount: record.file_count,
    unstable: record.unstable,
  };
}
