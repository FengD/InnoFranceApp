import { useState } from "react";
import type { SettingsResponse } from "../types";

interface SettingsPanelProps {
  settings: SettingsResponse;
  onUpdate: (patch: {
    parallel_enabled?: boolean;
    max_concurrent?: number;
  }) => Promise<void>;
  onClose: () => void;
}

export function SettingsPanel({
  settings,
  onUpdate,
  onClose,
}: SettingsPanelProps) {
  const [parallel, setParallel] = useState(settings.parallel_enabled);
  const [maxConcurrent, setMaxConcurrent] = useState(settings.max_concurrent);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onUpdate({
        parallel_enabled: parallel,
        max_concurrent: maxConcurrent,
      });
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings-panel" role="dialog" aria-label="Settings">
      <div className="settings-panel-inner">
        <h3>Settings</h3>
        <p className="muted">
          Control whether multiple pipelines can run in parallel and how many.
        </p>
        <div className="form-group">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={parallel}
              onChange={(e) => setParallel(e.target.checked)}
            />
            Allow parallel execution
          </label>
          <p className="muted" style={{ marginTop: "0.25rem", marginBottom: 0 }}>
            When enabled, up to the selected number of pipelines run at once.
            When disabled, only one runs at a time; others wait in queue.
          </p>
        </div>
        <div className="form-group">
          <label htmlFor="max-concurrent">Max concurrent pipelines</label>
          <select
            id="max-concurrent"
            value={maxConcurrent}
            onChange={(e) => setMaxConcurrent(Number(e.target.value))}
            disabled={!parallel}
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
          <p className="muted" style={{ marginTop: "0.25rem", marginBottom: 0 }}>
            Applies when parallel execution is enabled. Max queue size is{" "}
            {settings.max_queued} (queued + running).
          </p>
        </div>
        <div className="settings-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
