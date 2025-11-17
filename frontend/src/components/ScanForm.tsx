import { FormEvent, useState } from "react";
import type { ScanRequest } from "../api";

interface ScanFormProps {
  onSubmit: (payload: ScanRequest) => Promise<void>;
  busy: boolean;
}

const defaultPayload: ScanRequest = {
  root_path: "/data",
  file_equality: "name_size",
  similarity_threshold: 0.8,
  structure_policy: "relative",
  force_case_insensitive: false,
  deletion_enabled: false,
  include_matrix: false,
  include_treemap: false,
};

export function ScanForm({ onSubmit, busy }: ScanFormProps) {
  const [form, setForm] = useState<ScanRequest>(defaultPayload);

  const update = <K extends keyof ScanRequest>(key: K, value: ScanRequest[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit(form);
  };

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <div className="panel-header">
        <div>
          <div className="panel-title">New Scan</div>
          <p className="muted">
            Point the scanner at a root folder, adjust matching strategy, then launch.
          </p>
        </div>
        <button
          type="submit"
          className="button primary"
          disabled={busy}
        >
          {busy ? "Scanning…" : "Launch Scan"}
        </button>
      </div>
      <div className="scan-form-fields">
        <div className="input-group">
          <label htmlFor="root_path">Root Path</label>
          <input
            id="root_path"
            required
            value={form.root_path}
            onChange={(event) => update("root_path", event.target.value)}
            placeholder="/data"
          />
        </div>
        <div className="input-group">
          <label htmlFor="file_equality">File Equality</label>
          <select
            id="file_equality"
            value={form.file_equality}
            onChange={(event) =>
              update("file_equality", event.target.value as ScanRequest["file_equality"])
            }
          >
            <option value="name_size">Name + Size</option>
            <option value="sha256">SHA-256 Hash</option>
          </select>
        </div>
        <div className="input-group">
          <label htmlFor="threshold">Min Similarity</label>
          <input
            id="threshold"
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={form.similarity_threshold ?? 0.8}
            onChange={(event) => update("similarity_threshold", Number(event.target.value))}
          />
        </div>
        <div className="input-group">
          <label htmlFor="structure_policy">Structure Policy</label>
          <select
            id="structure_policy"
            value={form.structure_policy}
            onChange={(event) =>
              update("structure_policy", event.target.value as ScanRequest["structure_policy"])
            }
          >
            <option value="relative">Relative Paths</option>
            <option value="bag_of_files">Bag of Files</option>
          </select>
        </div>
        <div className="input-group">
          <label htmlFor="concurrency">Concurrency Cap</label>
          <input
            id="concurrency"
            type="number"
            min={1}
            max={32}
            value={form.concurrency ?? ""}
            placeholder="auto"
            onChange={(event) =>
              update("concurrency", event.target.value ? Number(event.target.value) : undefined)
            }
          />
        </div>
        <div className="input-group">
          <label htmlFor="case_mode">Case Handling</label>
          <select
            id="case_mode"
            value={form.force_case_insensitive ? "ci" : "native"}
            onChange={(event) => update("force_case_insensitive", event.target.value === "ci")}
          >
            <option value="native">Respect Filesystem</option>
            <option value="ci">Force Case-Insensitive</option>
          </select>
        </div>
        <div className="input-group">
          <label htmlFor="deletion">Deletion Workflow</label>
          <select
            id="deletion"
            value={form.deletion_enabled ? "enabled" : "disabled"}
            onChange={(event) => update("deletion_enabled", event.target.value === "enabled")}
          >
            <option value="disabled">Disabled (safe)</option>
            <option value="enabled">Enabled (requires RW mount)</option>
          </select>
        </div>
        <div className="input-group">
          <label>Optional Insights</label>
          <div className="checkbox-stack">
            <label>
              <input
                type="checkbox"
                checked={form.include_matrix ?? false}
                onChange={(event) => update("include_matrix", event.target.checked)}
              />
              Generate similarity matrix (higher RAM)
            </label>
            <label>
              <input
                type="checkbox"
                checked={form.include_treemap ?? false}
                onChange={(event) => update("include_treemap", event.target.checked)}
              />
              Generate duplicate-density treemap
            </label>
          </div>
        </div>
      </div>
    </form>
  );
}
