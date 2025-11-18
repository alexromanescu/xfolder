import { useCallback, useEffect, useMemo, useState } from "react";
import {
  DeletionPlan,
  DeletionResult,
  FolderLabel,
  GroupDiff,
  GroupRecord,
  GroupContents,
  ScanProgress,
  ScanRequest,
  SimilarityMatrixResponse,
  TreemapResponse,
  WarningRecord,
  confirmDeletionPlan,
  createDeletionPlan,
  createScan,
  exportGroups,
  fetchGroupDiff,
  fetchGroupContents,
  fetchGroups,
  fetchScans,
  fetchSimilarityMatrix,
  fetchTreemap,
  cancelScan,
} from "./api";
import { formatDate, humanBytes, humanDuration, formatEta } from "./format";
import { MetricCard } from "./components/MetricCard";
import { ScanForm } from "./components/ScanForm";
import { GroupTable } from "./components/GroupTable";
import { TreeView } from "./components/TreeView";
import { SimilarityMatrixView } from "./components/SimilarityMatrix";
import { DensityTreemap } from "./components/DensityTreemap";
import { DiagnosticsDrawer } from "./components/DiagnosticsDrawer";
import { WarningsPanel } from "./components/WarningsPanel";
import { DiffModal } from "./components/DiffModal";
import { ComparisonPanel, ComparisonEntry } from "./components/ComparisonPanel";

type GroupTab = FolderLabel;

const TAB_ORDER: GroupTab[] = ["identical", "near_duplicate", "partial_overlap"];

export default function App() {
  const [scans, setScans] = useState<ScanProgress[]>([]);
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null);
  const [groupsByLabel, setGroupsByLabel] = useState<Record<GroupTab, GroupRecord[]>>({
    identical: [],
    near_duplicate: [],
    partial_overlap: [],
  });
  const [activeTab, setActiveTab] = useState<GroupTab>("identical");
  const [loadingScan, setLoadingScan] = useState(false);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [viewMode, setViewMode] = useState<"list" | "tree">("list");
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [plan, setPlan] = useState<DeletionPlan | null>(null);
  const [planResult, setPlanResult] = useState<DeletionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffData, setDiffData] = useState<GroupDiff | undefined>(undefined);
  const [matrix, setMatrix] = useState<SimilarityMatrixResponse | null>(null);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [treemap, setTreemap] = useState<TreemapResponse | null>(null);
  const [treemapLoading, setTreemapLoading] = useState(false);
  const [insightTab, setInsightTab] = useState<"matrix" | "treemap">("matrix");
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [comparisonEntries, setComparisonEntries] = useState<ComparisonEntry[]>([]);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonContents, setComparisonContents] = useState<GroupContents | null>(null);
  const [showMatchingEntries, setShowMatchingEntries] = useState(true);
  const [groupsPaneWidth, setGroupsPaneWidth] = useState<number | null>(null);

  const currentScan = useMemo<ScanProgress | null>(
    () => scans.find((item) => item.scan_id === selectedScanId) ?? (scans[0] ?? null),
    [scans, selectedScanId],
  );
  const matrixEnabled = currentScan?.include_matrix ?? false;
  const treemapEnabled = currentScan?.include_treemap ?? false;

  const progressValue = currentScan?.progress ?? null;
  const etaLabel = formatEta(currentScan?.eta_seconds ?? null);
  const elapsedLabel = currentScan ? humanDuration(currentScan.started_at, currentScan.completed_at) : "—";
  const phase = currentScan?.phase ?? "";
  const lastPath = currentScan?.last_path ?? "";
  const isRunning = currentScan?.status === "running";
  const isCancellable = currentScan?.status === "running";

  useEffect(() => {
    setSelectedPaths(new Set<string>());
    setPlan(null);
    setPlanResult(null);
    setSelectedGroupId(null);
    setComparisonEntries([]);
  }, [currentScan?.scan_id]);

  useEffect(() => {
    if (!currentScan) return;
    if (matrixEnabled && !treemapEnabled && insightTab !== "matrix") {
      setInsightTab("matrix");
      return;
    }
    if (!matrixEnabled && treemapEnabled && insightTab !== "treemap") {
      setInsightTab("treemap");
      return;
    }
    if (!matrixEnabled && !treemapEnabled && insightTab !== "matrix") {
      setInsightTab("matrix");
    }
  }, [currentScan?.scan_id, matrixEnabled, treemapEnabled, insightTab]);

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;

    const bootstrap = async () => {
      try {
        const latest = await fetchScans();
        if (cancelled) return;
        setScans((prev) => (scansEqual(prev, latest) ? prev : latest));
        setSelectedScanId((prev) => {
          if (prev && latest.some((scan) => scan.scan_id === prev)) {
            return prev;
          }
          return latest.length ? latest[0].scan_id : null;
        });
      } catch (cause) {
        console.error("Failed to fetch scans", cause);
      }
    };

    const connect = () => {
      source?.close();
      source = new EventSource("/api/scans/events");
      source.onmessage = (event) => {
        if (cancelled) return;
        try {
          const payload = JSON.parse(event.data) as { scans?: ScanProgress[] };
          if (!payload.scans) return;
          setScans((prev) => (scansEqual(prev, payload.scans!) ? prev : payload.scans!));
          setSelectedScanId((prev) => {
            if (prev && payload.scans!.some((scan) => scan.scan_id === prev)) {
              return prev;
            }
            return payload.scans!.length ? payload.scans![0].scan_id : null;
          });
        } catch (cause) {
          console.error("Failed to parse scan progress event", cause);
        }
      };
      source.onerror = () => {
        if (cancelled) return;
        source?.close();
        window.setTimeout(() => {
          if (!cancelled) connect();
        }, 4000);
      };
    };

    bootstrap();
    connect();

    return () => {
      cancelled = true;
      source?.close();
    };
  }, []);

  useEffect(() => {
    if (!currentScan || currentScan.status !== "completed") {
      return;
    }
    let cancelled = false;
    setLoadingGroups(true);
    const loadGroups = async () => {
      try {
        const [identical, near, partial] = await Promise.all([
          fetchGroups(currentScan.scan_id, "identical"),
          fetchGroups(currentScan.scan_id, "near_duplicate"),
          fetchGroups(currentScan.scan_id, "partial_overlap").catch(() => []),
        ]);
        if (!cancelled) {
          setGroupsByLabel({
            identical,
            near_duplicate: near,
            partial_overlap: partial,
          });
        }
      } catch (cause) {
        console.error("Failed to fetch groups", cause);
        if (!cancelled) setError("Failed to fetch similarity groups");
      } finally {
        if (!cancelled) setLoadingGroups(false);
      }
    };
    loadGroups();
    return () => {
      cancelled = true;
    };
  }, [currentScan]);

  useEffect(() => {
    if (!currentScan || currentScan.status !== "completed") {
      setMatrix(null);
      setTreemap(null);
      setMatrixLoading(false);
      setTreemapLoading(false);
      return;
    }
    let cancelled = false;

    if (currentScan.include_matrix) {
      setMatrixLoading(true);
      fetchSimilarityMatrix(currentScan.scan_id, { min_similarity: 0.6, limit: 250 })
        .then((response) => {
          if (!cancelled) setMatrix(response);
        })
        .catch((cause) => {
          console.error("Failed to fetch matrix", cause);
          if (!cancelled) setMatrix(null);
        })
        .finally(() => {
          if (!cancelled) setMatrixLoading(false);
        });
    } else {
      setMatrix(null);
      setMatrixLoading(false);
    }

    if (currentScan.include_treemap) {
      setTreemapLoading(true);
      fetchTreemap(currentScan.scan_id)
        .then((response) => {
          if (!cancelled) setTreemap(response);
        })
        .catch((cause) => {
          console.error("Failed to fetch treemap", cause);
          if (!cancelled) setTreemap(null);
        })
        .finally(() => {
          if (!cancelled) setTreemapLoading(false);
        });
    } else {
      setTreemap(null);
      setTreemapLoading(false);
    }

    return () => {
      cancelled = true;
    };
  }, [currentScan]);

  const handleScanLaunch = useCallback(
    async (payload: ScanRequest) => {
      setError(null);
      setLoadingScan(true);
      try {
        const started = await createScan(payload);
        setScans((prev) => [started, ...prev]);
        setSelectedScanId(started.scan_id);
      } catch (cause) {
        console.error("Failed to start scan", cause);
        setError("Unable to start scan. Check server logs for details.");
      } finally {
        setLoadingScan(false);
      }
    },
    [],
  );

  const togglePath = (path: string) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  const handleExport = async (format: "json" | "csv" | "md") => {
    if (!currentScan) return;
    try {
      const blob = await exportGroups(currentScan.scan_id, format);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `xfolder-${currentScan.scan_id}.${format}`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (cause) {
      console.error("Export failed", cause);
      setError("Export failed. Please retry.");
    }
  };

  const handlePlan = async () => {
    if (!currentScan || selectedPaths.size === 0) return;
    try {
      const root = currentScan.root_path.replace(/\/+$/, "");
      const relPaths = Array.from(selectedPaths).map((absolutePath) => {
        if (absolutePath.startsWith(root)) {
          const trimmed = absolutePath.slice(root.length);
          return trimmed.startsWith("/") ? trimmed.slice(1) : trimmed || ".";
        }
        return absolutePath;
      });
      const created = await createDeletionPlan(currentScan.scan_id, relPaths);
      setPlan(created);
      setPlanResult(null);
      setError(null);
    } catch (cause) {
      console.error("Deletion plan failed", cause);
      setError("Could not create deletion plan. Confirm deletion is enabled and mounts are RW.");
    }
  };

  const handleSelectGroup = useCallback((group: GroupRecord) => {
    setSelectedGroupId(group.group_id);
  }, []);

  const handleCompare = useCallback(
    async (group: GroupRecord, memberRelative: string) => {
      if (!currentScan) return;
      setDiffOpen(true);
      setDiffLoading(true);
      setDiffData(undefined);
      try {
        const diff = await fetchGroupDiff(
          currentScan.scan_id,
          group.group_id,
          group.members[0].relative_path,
          memberRelative,
        );
        setDiffData(diff);
      } catch (cause) {
        console.error("Failed to load diff", cause);
        setDiffData(undefined);
        setError("Unable to load comparison diff. See server logs for details.");
      } finally {
        setDiffLoading(false);
      }
    },
    [currentScan],
  );

  const handleGroupsResizeMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const container = event.currentTarget.parentElement;
      if (!container) {
        return;
      }
      const rect = container.getBoundingClientRect();
      const startX = event.clientX;
      const startWidth = groupsPaneWidth ?? rect.width / 3;

      const onMove = (moveEvent: MouseEvent) => {
        const delta = moveEvent.clientX - startX;
        const next = Math.min(rect.width * 0.8, Math.max(240, startWidth + delta));
        setGroupsPaneWidth(next);
      };

      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };

      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [groupsPaneWidth],
  );

  const handleConfirmPlan = async () => {
    if (!plan) return;
    try {
      const result = await confirmDeletionPlan(plan.plan_id, plan.token);
      setPlanResult(result);
      setSelectedPaths(new Set<string>());
      setPlan(null);
    } catch (cause) {
      console.error("Confirm plan failed", cause);
      setError("Failed to apply deletion plan. Check permissions or token expiry.");
    }
  };

  const currentWarnings: WarningRecord[] = currentScan?.warnings ?? [];

  const currentGroups =
    activeTab === "identical"
      ? [...groupsByLabel.identical, ...groupsByLabel.near_duplicate]
      : groupsByLabel[activeTab] ?? [];

  const allGroups = useMemo(
    () => [...groupsByLabel.identical, ...groupsByLabel.near_duplicate, ...groupsByLabel.partial_overlap],
    [groupsByLabel],
  );
  const selectedComparisonGroup = useMemo(() => {
    if (!selectedGroupId) return null;
    return allGroups.find((group) => group.group_id === selectedGroupId) ?? null;
  }, [selectedGroupId, allGroups]);

  useEffect(() => {
    setComparisonEntries([]);
    setComparisonContents(null);
    if (!selectedComparisonGroup || selectedComparisonGroup.members.length < 2 || !currentScan) {
      setComparisonLoading(false);
      return;
    }
    const canonical = selectedComparisonGroup.members[0];
    if (!canonical) {
      setComparisonLoading(false);
      return;
    }
    let cancelled = false;
    setComparisonLoading(true);
    const load = async () => {
      const entries = await Promise.all(
        selectedComparisonGroup.members.slice(1).map(async (member) => {
          try {
            const diff = await fetchGroupDiff(
              currentScan.scan_id,
              selectedComparisonGroup.group_id,
              canonical.relative_path,
              member.relative_path,
            );
            return { member, diff };
          } catch (cause) {
            const message = cause instanceof Error ? cause.message : "Unable to load differences";
            return { member, error: message };
          }
        }),
      );
      if (!cancelled) {
        setComparisonEntries(entries);
        setComparisonLoading(false);
      }
    };
    load().catch(() => {
      if (!cancelled) {
        setComparisonEntries([]);
        setComparisonLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedComparisonGroup, currentScan]);

  useEffect(() => {
    if (!selectedComparisonGroup || !currentScan) {
      setComparisonContents(null);
      return;
    }
    let cancelled = false;
    fetchGroupContents(currentScan.scan_id, selectedComparisonGroup.group_id)
      .then((response) => {
        if (!cancelled) setComparisonContents(response);
      })
      .catch((cause) => {
        console.error("Failed to fetch folder contents", cause);
        if (!cancelled) setComparisonContents(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedComparisonGroup, currentScan]);

  const totalPotentialReclaim = useMemo(() => {
    if (!groupsByLabel.identical.length && !groupsByLabel.near_duplicate.length) return 0;
    return [...groupsByLabel.identical, ...groupsByLabel.near_duplicate].reduce((sum, group) => {
      if (group.members.length < 2) return sum;
      return (
        sum +
        group.members
          .slice(1)
          .reduce((acc, member) => acc + Number(member.total_bytes || 0), 0)
      );
    }, 0);
  }, [groupsByLabel]);

  const summaryStats = {
    folders: currentScan?.stats?.folders_scanned ?? 0,
    files: currentScan?.stats?.files_scanned ?? 0,
    workers: currentScan?.stats?.workers ?? 0,
  };
  const insightsAvailable = currentScan?.status === "completed" && (matrixEnabled || treemapEnabled);
  const shouldShowMatrix = matrixEnabled && (!treemapEnabled || insightTab === "matrix");
  const shouldShowTreemap = treemapEnabled && (!matrixEnabled || insightTab === "treemap");

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-content">
          <div>
            <h1>Folder Similarity Scanner</h1>
            <p>
              Discover duplicate and near-identical folder structures, export reports, and reclaim disk
              space with a guarded deletion workflow.
            </p>
          </div>
          <button className="button secondary" type="button" onClick={() => setDiagnosticsOpen(true)}>
            Diagnostics
          </button>
        </div>
      </header>
      <main className="app-content">
        <div className="top-layout">
          <div className="top-left">
            <ScanForm onSubmit={handleScanLaunch} busy={loadingScan} />
          </div>
          <div className="top-right">
            {currentScan ? (
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <div className="panel-title">Active Scans</div>
                    <p className="muted">Pick a scan to inspect its groups, warnings, and exports.</p>
                  </div>
                </div>
                <div className="active-scans-body">
                  <div className="active-scans-table">
                    <div className="scroll-container">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Status</th>
                            <th>Root</th>
                            <th>Started</th>
                            <th>Completed</th>
                            <th>Duration</th>
                            <th>Similarity</th>
                          </tr>
                        </thead>
                        <tbody>
                          {scans.map((scan) => (
                            <tr
                              key={scan.scan_id}
                              onClick={() => setSelectedScanId(scan.scan_id)}
                              style={{
                                cursor: "pointer",
                                background:
                                  scan.scan_id === currentScan.scan_id
                                    ? "rgba(56, 189, 248, 0.08)"
                                    : undefined,
                              }}
                            >
                              <td>
                                <span className={`status-dot ${scan.status}`} />
                                <span style={{ marginLeft: 12, textTransform: "capitalize" }}>
                                  {scan.status}
                                </span>
                              </td>
                              <td>
                                <div>{scan.root_path}</div>
                                <div className="muted">#{scan.scan_id}</div>
                              </td>
                              <td>{formatDate(scan.started_at)}</td>
                              <td>{formatDate(scan.completed_at)}</td>
                              <td>{humanDuration(scan.started_at, scan.completed_at)}</td>
                              <td>
                                {scan.status === "completed"
                                  ? scan.scan_id === currentScan?.scan_id
                                    ? `${groupsByLabel.identical.length + groupsByLabel.near_duplicate.length} groups`
                                    : "Ready"
                                  : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                  <div className="card-grid">
                    <MetricCard title="Folders Scanned" value={summaryStats.folders.toLocaleString()} />
                    <MetricCard title="Files Scanned" value={summaryStats.files.toLocaleString()} />
                    <MetricCard
                      title="Active Workers"
                      value={summaryStats.workers ? summaryStats.workers.toString() : "auto"}
                    />
                    <MetricCard title="Potential Reclaim" value={humanBytes(totalPotentialReclaim)} />
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        {isRunning ? (
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="panel-title">Scan Progress</div>
                <p className="muted">
                  Scanned {currentScan?.stats?.folders_scanned ?? 0} folders ·{" "}
                  {currentScan?.stats?.files_scanned ?? 0} files — elapsed {elapsedLabel} — {etaLabel}
                </p>
                {phase || lastPath ? (
                  <p className="muted">Phase: {phase || "walking"}{lastPath ? ` — at ${lastPath}` : ""}</p>
                ) : null}
              </div>
              <div className="panel-actions" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div className="muted" style={{ fontWeight: 600 }}>
                  {progressValue != null ? `${Math.round(progressValue * 100)}%` : "Working…"}
                </div>
                {isCancellable && currentScan ? (
                  <button
                    className="button secondary"
                    type="button"
                    onClick={async () => {
                      try {
                        const updated = await cancelScan(currentScan.scan_id);
                        setScans((prev) =>
                          prev.map((scan) => (scan.scan_id === updated.scan_id ? updated : scan)),
                        );
                      } catch (cause) {
                        console.error("Failed to cancel scan", cause);
                        setError("Unable to stop scan. Check server logs for details.");
                      }
                    }}
                  >
                    Stop scan
                  </button>
                ) : null}
              </div>
            </div>
            <div className={`progress-bar${progressValue == null ? " indeterminate" : ""}`}>
              <div
                className={`progress-bar-fill${progressValue == null ? " indeterminate" : ""}`}
                style={progressValue != null ? { width: `${Math.max(2, progressValue * 100)}%` } : undefined}
              />
            </div>
            {currentScan?.phases?.length ? (
              <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
                {currentScan.phases.map((phaseProgress) => {
                  const label =
                    phaseProgress.name === "walking"
                      ? "Filesystem walk"
                      : phaseProgress.name === "aggregating"
                        ? "Aggregation"
                        : phaseProgress.name === "grouping"
                          ? "Grouping"
                          : phaseProgress.name;
                  const isWalkingPhase = phaseProgress.name === "walking";
                  const value = phaseProgress.progress ?? null;
                  const isCompleted = phaseProgress.status === "completed";
                  const isRunningPhase = phaseProgress.status === "running";
                  const percent = value != null ? Math.round(value * 100) : null;
                  return (
                    <div key={phaseProgress.name} style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8, alignItems: "center" }}>
                      <div
                        className="muted"
                        style={{
                          fontSize: 13,
                          fontWeight: isRunningPhase ? 600 : 400,
                        }}
                      >
                        {isCompleted ? "✔" : isRunningPhase ? "●" : "○"} {label}
                        {!isWalkingPhase && percent != null ? ` — ${percent}%` : ""}
                      </div>
                      {isWalkingPhase ? (
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-start", minHeight: 12 }}>
                          {isRunningPhase ? <div className="spinner" aria-label="Scanning filesystem" /> : null}
                        </div>
                      ) : (
                        <div className={`progress-bar phase${value == null ? " indeterminate" : ""}`}>
                          <div
                            className={`progress-bar-fill${value == null ? " indeterminate" : ""}`}
                            style={value != null ? { width: `${Math.max(2, value * 100)}%` } : undefined}
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        ) : null}

        {currentScan?.status === "completed" ? (
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="panel-title">Similarity Explorer</div>
                <p className="muted">
                  Review duplicate groups on the left and inspect detailed folder comparisons on the right.
                </p>
              </div>
              <div className="panel-actions">
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => handleExport("json")}
                >
                  Export JSON
                </button>
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => handleExport("csv")}
                >
                  Export CSV
                </button>
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => handleExport("md")}
                >
                  Export Markdown
                </button>
              </div>
            </div>
            <div className="groups-comparison-layout">
              <div
                className="groups-panel"
                style={{
                  flex: groupsPaneWidth != null ? `0 0 ${groupsPaneWidth}px` : "0 0 33.333%",
                }}
              >
                <div className="tab-strip">
                  {TAB_ORDER.map((tab) => (
                    <div
                      key={tab}
                      className={`tab ${activeTab === tab ? "active" : ""}`}
                      onClick={() => setActiveTab(tab)}
                      role="tab"
                    >
                      {tab === "identical"
                        ? "Identical"
                        : tab === "near_duplicate"
                          ? "Near Duplicate"
                          : "Overlap Explorer"}
                    </div>
                  ))}
                  <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                    <button
                      className={`button secondary`}
                      type="button"
                      onClick={() => setViewMode("list")}
                    >
                      List
                    </button>
                    <button
                      className={`button secondary`}
                      type="button"
                      onClick={() => setViewMode("tree")}
                    >
                      Tree
                    </button>
                  </div>
                </div>
                <div className="groups-table-shell">
                  {loadingGroups ? (
                    <p className="muted" style={{ padding: 12 }}>
                      Loading groups…
                    </p>
                  ) : viewMode === "list" ? (
                    <GroupTable
                      groups={currentGroups}
                      rootPath={currentScan.root_path}
                      selected={selectedPaths}
                      onToggle={togglePath}
                      emptyLabel="No matches detected for this view yet."
                      onCompare={handleCompare}
                      onSelectGroup={handleSelectGroup}
                      selectedGroupId={selectedGroupId}
                    />
                  ) : (
                    <TreeView
                      rootPath={currentScan.root_path}
                      groups={currentGroups}
                      onSelectGroup={handleSelectGroup}
                      selectedGroupId={selectedGroupId}
                    />
                  )}
                </div>
                <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center" }}>
                  <button
                    className="button primary"
                    type="button"
                    disabled={!selectedPaths.size || !!plan}
                    onClick={handlePlan}
                  >
                    Plan Quarantine ({selectedPaths.size})
                  </button>
                  {plan ? (
                    <button
                      className="button danger"
                      type="button"
                      onClick={handleConfirmPlan}
                    >
                      Confirm &amp; Move ({humanBytes(plan.reclaimable_bytes)})
                    </button>
                  ) : null}
                  {plan ? (
                    <span className="muted">
                      Token {plan.token.substring(0, 8)}… expires {formatDate(plan.expires_at)}
                    </span>
                  ) : null}
                  {planResult ? (
                    <span className="pill">
                      Moved {planResult.moved_count} items · {humanBytes(planResult.bytes_moved)}
                    </span>
                  ) : null}
                </div>
              </div>
              <div
                className="groups-resize-handle"
                onMouseDown={handleGroupsResizeMouseDown}
              />
              <div style={{ flex: "1 1 0", minWidth: 320, minHeight: 0 }}>
                <ComparisonPanel
                  group={selectedComparisonGroup}
                  entries={comparisonEntries}
                  contents={comparisonContents}
                  loading={comparisonLoading}
                  showMatches={showMatchingEntries}
                  onToggleShowMatches={() => setShowMatchingEntries((prev) => !prev)}
                  onClear={() => setSelectedGroupId(null)}
                />
              </div>
            </div>
          </div>
        ) : (
          <div className="panel">
            <div className="panel-title">Similarity Groups</div>
            <p className="muted">Run a scan to populate this view.</p>
          </div>
        )}

        {insightsAvailable ? (
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="panel-title">Visual Insights</div>
                <p className="muted">
                  {matrixEnabled && treemapEnabled
                    ? "Inspect adjacency heatmaps or the duplicate-density treemap."
                    : matrixEnabled
                      ? "Adjacency heatmap was requested for this scan."
                      : "Duplicate-density treemap was requested for this scan."}
                </p>
              </div>
            </div>
            {matrixEnabled && treemapEnabled ? (
              <div className="tab-strip">
                <div className={`tab ${insightTab === "matrix" ? "active" : ""}`} onClick={() => setInsightTab("matrix")}>
                  Matrix
                </div>
                <div className={`tab ${insightTab === "treemap" ? "active" : ""}`} onClick={() => setInsightTab("treemap")}>
                  Treemap
                </div>
              </div>
            ) : null}
            {shouldShowMatrix ? (
              <SimilarityMatrixView entries={matrix?.entries ?? []} loading={matrixLoading} />
            ) : null}
            {shouldShowTreemap ? (
              <DensityTreemap tree={treemap?.tree ?? null} loading={treemapLoading} />
            ) : null}
          </div>
        ) : currentScan?.status === "completed" ? (
          <div className="panel">
            <div className="panel-title">Visual Insights</div>
            <p className="muted">This scan skipped matrix/treemap generation. Enable the checkboxes before launching to collect these artifacts.</p>
          </div>
        ) : null}

        <WarningsPanel warnings={currentWarnings} />

        {error ? (
          <div className="panel" style={{ borderColor: "rgba(248, 113, 113, 0.4)" }}>
            <div className="panel-title">Something went wrong</div>
            <p className="muted">{error}</p>
          </div>
        ) : null}
        <DiffModal
          open={diffOpen}
          diff={diffData}
          loading={diffLoading}
          onClose={() => {
            setDiffOpen(false);
            setDiffData(undefined);
          }}
        />
        <DiagnosticsDrawer open={diagnosticsOpen} onClose={() => setDiagnosticsOpen(false)} />
      </main>
    </div>
  );
}

function scansEqual(a: ScanProgress[], b: ScanProgress[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    const left = a[i];
    const right = b[i];
    if (
      left.scan_id !== right.scan_id ||
      left.status !== right.status ||
      left.root_path !== right.root_path ||
      left.started_at !== right.started_at ||
      (left.completed_at ?? "") !== (right.completed_at ?? "") ||
      (left.progress ?? null) !== (right.progress ?? null) ||
      (left.eta_seconds ?? null) !== (right.eta_seconds ?? null) ||
      left.include_matrix !== right.include_matrix ||
      left.include_treemap !== right.include_treemap ||
      !statsEqual(left.stats ?? {}, right.stats ?? {})
    ) {
      return false;
    }
  }
  return true;
}

function statsEqual(
  a: Record<string, number>,
  b: Record<string, number>,
): boolean {
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) {
    return false;
  }
  for (const key of aKeys) {
    if (a[key] !== b[key]) {
      return false;
    }
  }
  return true;
}
