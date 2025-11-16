import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./api", () => {
  const noop = (..._args: unknown[]) => Promise.resolve();
  return {
    createScan: vi.fn(noop),
    fetchScans: vi.fn().mockResolvedValue([]),
    fetchGroups: vi.fn().mockResolvedValue([]),
    fetchGroupDiff: vi.fn().mockResolvedValue({
      left: {
        path: "",
        relative_path: ".",
        total_bytes: 0,
        file_count: 0,
        unstable: false,
      },
      right: {
        path: "",
        relative_path: ".",
        total_bytes: 0,
        file_count: 0,
        unstable: false,
      },
      only_left: [],
      only_right: [],
      mismatched: [],
    }),
    exportGroups: vi.fn(() => Promise.resolve(new Blob())),
    createDeletionPlan: vi.fn(noop),
    confirmDeletionPlan: vi.fn(noop),
    fetchSimilarityMatrix: vi.fn().mockResolvedValue({
      scan_id: "test",
      generated_at: new Date().toISOString(),
      root_path: "/data",
      min_similarity: 0.6,
      total_entries: 0,
      entries: [],
    }),
    fetchTreemap: vi.fn().mockResolvedValue({
      scan_id: "test",
      generated_at: new Date().toISOString(),
      root_path: "/data",
      tree: {
        path: ".",
        name: ".",
        total_bytes: 0,
        duplicate_bytes: 0,
        identical_groups: 0,
        near_groups: 0,
        children: [],
      },
    }),
    fetchGroupContents: vi.fn().mockResolvedValue({
      group_id: "g_test",
      canonical: { relative_path: ".", entries: [] },
      duplicates: [],
    }),
  };
});

describe("App bootstrap", () => {
  it("renders the landing state without crashing", async () => {
    render(<App />);
    expect(await screen.findByText(/Folder Similarity Scanner/)).toBeInTheDocument();
    expect(await screen.findByText(/Run a scan to populate this view/)).toBeInTheDocument();
  });
});
