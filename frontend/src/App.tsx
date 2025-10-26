import { useCallback, useEffect, useMemo, useState } from "react";
import {
  DeletionPlan,
  DeletionResult,
  FolderLabel,
  GroupRecord,
  ScanProgress,
  ScanRequest,
  WarningRecord,
  confirmDeletionPlan,
  createDeletionPlan,
  createScan,
  exportGroups,
  fetchGroups,
  fetchScans,
} from "./api";
import { formatDate, humanBytes, humanDuration } from "./format";
import { MetricCard } from "./components/MetricCard";
import { ScanForm } from "./components/ScanForm";
import { GroupTable } from "./components/GroupTable";
import { WarningsPanel } from "./components/WarningsPanel";

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
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [plan, setPlan] = useState<DeletionPlan | null>(null);
  const [planResult, setPlanResult] = useState<DeletionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const currentScan = useMemo<ScanProgress | null>(
    () => scans.find((item) => item.scan_id === selectedScanId) ?? (scans[0] ?? null),
    [scans, selectedScanId],
  );

  useEffect(() => {
    setSelectedPaths(new Set<string>());
    setPlan(null);
    setPlanResult(null);
  }, [currentScan?.scan_id]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const latest = await fetchScans();
        if (cancelled) return;
        setScans(latest);
        setSelectedScanId((prev) => {
          if (prev) return prev;
          return latest.length ? latest[0].scan_id : null;
        });
      } catch (cause) {
        console.error("Failed to fetch scans", cause);
      }
    };

    load();
    const timer = window.setInterval(load, 4000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
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

  const currentGroups = groupsByLabel[activeTab] ?? [];

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

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Folder Similarity Scanner</h1>
        <p>
          Discover duplicate and near-identical folder structures, export reports, and reclaim disk
          space with a guarded deletion workflow.
        </p>
      </header>
      <main className="app-content">
        <ScanForm onSubmit={handleScanLaunch} busy={loadingScan} />

        {currentScan ? (
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="panel-title">Active Scans</div>
                <p className="muted">Pick a scan to inspect its groups, warnings, and exports.</p>
              </div>
            </div>
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
        ) : null}

        <div className="card-grid">
          <MetricCard title="Folders Scanned" value={summaryStats.folders.toLocaleString()} />
          <MetricCard title="Files Scanned" value={summaryStats.files.toLocaleString()} />
          <MetricCard
            title="Active Workers"
            value={summaryStats.workers ? summaryStats.workers.toString() : "auto"}
          />
          <MetricCard title="Potential Reclaim" value={humanBytes(totalPotentialReclaim)} />
        </div>

        {currentScan?.status === "completed" ? (
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="panel-title">Similarity Groups</div>
                <p className="muted">
                  Toggle between identical clones and near matches. Select folders to plan a safe
                  quarantine move.
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
            </div>
            {loadingGroups ? (
              <p className="muted">Loading groups…</p>
            ) : (
              <GroupTable
                groups={currentGroups}
                selected={selectedPaths}
                onToggle={togglePath}
                emptyLabel="No matches detected for this view yet."
              />
            )}
            <div style={{ marginTop: 18, display: "flex", gap: 12 }}>
              <button
                className="button primary"
                type="button"
                disabled={!selectedPaths.size || !!plan}
                onClick={handlePlan}
              >
                Plan Quarantine ({selectedPaths.size})
              </button>
              {plan ? (
                <button className="button danger" type="button" onClick={handleConfirmPlan}>
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
        ) : (
          <div className="panel">
            <div className="panel-title">Similarity Groups</div>
            <p className="muted">Run a scan to populate this view.</p>
          </div>
        )}

        <WarningsPanel warnings={currentWarnings} />

        {error ? (
          <div className="panel" style={{ borderColor: "rgba(248, 113, 113, 0.4)" }}>
            <div className="panel-title">Something went wrong</div>
            <p className="muted">{error}</p>
          </div>
        ) : null}
      </main>
    </div>
  );
}
