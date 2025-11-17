import axios from "axios";

export type ScanStatus = "pending" | "running" | "completed" | "failed";
export type FolderLabel = "identical" | "near_duplicate" | "partial_overlap";

export interface ScanRequest {
  root_path: string;
  include?: string[];
  exclude?: string[];
  file_equality?: "name_size" | "sha256";
  similarity_threshold?: number;
  force_case_insensitive?: boolean;
  structure_policy?: "relative" | "bag_of_files";
  concurrency?: number;
  deletion_enabled?: boolean;
  include_matrix?: boolean;
  include_treemap?: boolean;
}

export interface WarningRecord {
  path: string;
  type: "permission" | "unstable" | "io_error";
  message: string;
}

export interface ScanProgress {
  scan_id: string;
  status: ScanStatus;
  started_at: string;
  completed_at?: string;
  warnings: WarningRecord[];
  root_path: string;
  stats: Record<string, number>;
  progress?: number | null;
  eta_seconds?: number | null;
  phase?: string;
  last_path?: string | null;
  phases?: PhaseProgress[];
  include_matrix: boolean;
  include_treemap: boolean;
}

export interface PhaseProgress {
  name: string;
  status: "pending" | "running" | "completed";
  progress?: number | null;
}

export interface ResourceStats {
  cpu_cores: number;
  load_1m: number;
  process_rss_bytes: number;
  process_read_bytes?: number | null;
  process_write_bytes?: number | null;
}

export interface FolderRecord {
  path: string;
  relative_path: string;
  total_bytes: number;
  file_count: number;
  unstable: boolean;
}

export interface PairwiseSimilarity {
  a: number;
  b: number;
  similarity: number;
}

export interface DivergenceRecord {
  path_a: string;
  path_b: string;
  delta_bytes: number;
}

export interface GroupRecord {
  group_id: string;
  label: FolderLabel;
  canonical_path: string;
  members: FolderRecord[];
  pairwise_similarity: PairwiseSimilarity[];
  divergences: DivergenceRecord[];
  suppressed_descendants: boolean;
}

export interface DiffEntry {
  path: string;
  bytes: number;
}

export interface MismatchEntry {
  path: string;
  left_bytes: number;
  right_bytes: number;
}

export interface GroupDiff {
  left: FolderRecord;
  right: FolderRecord;
  only_left: DiffEntry[];
  only_right: DiffEntry[];
  mismatched: MismatchEntry[];
}

export interface FolderEntry {
  path: string;
  bytes: number;
}

export interface MemberContents {
  relative_path: string;
  entries: FolderEntry[];
}

export interface GroupContents {
  group_id: string;
  canonical: MemberContents;
  duplicates: MemberContents[];
}

export interface SimilarityMatrixEntry {
  group_id: string;
  label: FolderLabel;
  left: FolderRecord;
  right: FolderRecord;
  similarity: number;
  combined_bytes: number;
  reclaimable_bytes: number;
}

export interface SimilarityMatrixResponse {
  scan_id: string;
  generated_at: string;
  root_path: string;
  min_similarity: number;
  total_entries: number;
  entries: SimilarityMatrixEntry[];
}

export interface TreemapNode {
  path: string;
  name: string;
  total_bytes: number;
  duplicate_bytes: number;
  identical_groups: number;
  near_groups: number;
  children: TreemapNode[];
}

export interface TreemapResponse {
  scan_id: string;
  generated_at: string;
  root_path: string;
  tree: TreemapNode;
}

export interface DeletionPlan {
  plan_id: string;
  token: string;
  reclaimable_bytes: number;
  queue: string[];
  root: string;
  quarantine_root: string;
  expires_at: string;
}

export interface DeletionResult {
  plan_id: string;
  moved_count: number;
  bytes_moved: number;
  root: string;
  quarantine_root: string;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  level_no: number;
  message: string;
  logger: string;
}

const api = axios.create({
  baseURL: "/api",
  timeout: 60000,
});

export async function createScan(request: ScanRequest): Promise<ScanProgress> {
  const response = await api.post<ScanProgress>("/scans", request);
  return response.data;
}

export async function fetchScans(): Promise<ScanProgress[]> {
  const response = await api.get<ScanProgress[]>("/scans");
  return response.data;
}

export async function fetchGroups(
  scanId: string,
  label?: FolderLabel,
): Promise<GroupRecord[]> {
  const response = await api.get<GroupRecord[]>(`/scans/${scanId}/groups`, {
    params: label ? { label } : undefined,
  });
  return response.data;
}

export async function exportGroups(
  scanId: string,
  format: "json" | "csv" | "md",
): Promise<Blob> {
  const response = await api.post<ArrayBuffer>(`/scans/${scanId}/export`, null, {
    params: { fmt: format },
    responseType: "arraybuffer",
  });
  return new Blob([response.data], {
    type:
      format === "json"
        ? "application/json"
        : format === "csv"
          ? "text/csv"
          : "text/markdown",
  });
}

export async function createDeletionPlan(
  scanId: string,
  paths: string[],
): Promise<DeletionPlan> {
  const response = await api.post<DeletionPlan>(`/scans/${scanId}/deletion/plan`, {
    paths,
  });
  return response.data;
}

export async function confirmDeletionPlan(
  planId: string,
  token: string,
): Promise<DeletionResult> {
  const response = await api.post<DeletionResult>(`/deletions/${planId}/confirm`, {
    token,
  });
  return response.data;
}

export async function fetchGroupDiff(
  scanId: string,
  groupId: string,
  left: string,
  right: string,
): Promise<GroupDiff> {
  const response = await api.get<GroupDiff>(`/scans/${scanId}/groups/${groupId}/diff`, {
    params: { left, right },
  });
  return response.data;
}

interface MatrixParams {
  min_similarity?: number;
  limit?: number;
  offset?: number;
}

export async function fetchSimilarityMatrix(
  scanId: string,
  params?: MatrixParams,
): Promise<SimilarityMatrixResponse> {
  const response = await api.get<SimilarityMatrixResponse>(`/scans/${scanId}/matrix`, {
    params,
  });
  return response.data;
}

export async function fetchTreemap(scanId: string): Promise<TreemapResponse> {
  const response = await api.get<TreemapResponse>(`/scans/${scanId}/density/treemap`);
  return response.data;
}

export async function fetchGroupContents(scanId: string, groupId: string): Promise<GroupContents> {
  const response = await api.get<GroupContents>(`/scans/${scanId}/groups/${groupId}/contents`);
  return response.data;
}

export async function fetchResources(): Promise<ResourceStats> {
  const response = await api.get<ResourceStats>("/system/resources");
  return response.data;
}
