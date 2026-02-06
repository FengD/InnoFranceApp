import { useState } from "react";
import { uploadAsset } from "../api";
import type { SettingsResponse } from "../types";

interface SettingsPanelProps {
  settings: SettingsResponse;
  onUpdate: (patch: {
    parallel_enabled?: boolean;
    max_concurrent?: number;
    tags?: string[];
    api_keys?: Record<string, string>;
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
  const [tags, setTags] = useState<string[]>(settings.tags ?? []);
  const [tagInput, setTagInput] = useState("");
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [assetSelections, setAssetSelections] = useState<Record<string, string>>(
    settings.asset_selections ?? {}
  );
  const [uploadingAsset, setUploadingAsset] = useState<string | null>(null);
  const [assetError, setAssetError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const trimmedKeys: Record<string, string> = {};
      Object.entries(apiKeys).forEach(([key, value]) => {
        const trimmed = value.trim();
        if (trimmed) trimmedKeys[key] = trimmed;
      });
      await onUpdate({
        parallel_enabled: parallel,
        max_concurrent: maxConcurrent,
        tags,
        api_keys: Object.keys(trimmedKeys).length ? trimmedKeys : undefined,
        asset_selections: assetSelections,
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
            <option value={4}>4</option>
            <option value={5}>5</option>
          </select>
          <p className="muted" style={{ marginTop: "0.25rem", marginBottom: 0 }}>
            Applies when parallel execution is enabled. Max queue size is{" "}
            {settings.max_queued} (queued + running).
          </p>
        </div>
        <div className="form-group">
          <label>Provider API keys</label>
          <p className="muted" style={{ marginTop: "0.25rem" }}>
            Required for cloud providers. Local providers (Ollama/SGLang/VLLM) work without keys.
          </p>
          <div className="api-key-list">
            {[
              { key: "openai", label: "OpenAI", required: true },
              { key: "deepseek", label: "DeepSeek", required: true },
              { key: "qwen", label: "Qwen", required: true },
              { key: "glm", label: "GLM", required: true },
            ].map((provider) => {
              const source = settings.provider_key_source?.[provider.key] ?? "none";
              const statusLabel =
                source === "setting"
                  ? "Configured"
                  : source === "env"
                    ? "Env"
                    : "Missing";
              return (
                <div key={provider.key} className="api-key-row">
                  <div className="api-key-label">
                    <span>{provider.label}</span>
                    <span
                      className={`api-key-status${
                        source === "setting" || source === "env" ? " is-active" : ""
                      }`}
                    >
                      {statusLabel}
                    </span>
                  </div>
                  <input
                    type="password"
                    placeholder="Set API key"
                    value={apiKeys[provider.key] ?? ""}
                    onChange={(e) =>
                      setApiKeys((prev) => ({ ...prev, [provider.key]: e.target.value }))
                    }
                  />
                </div>
              );
            })}
          </div>
        </div>
        <div className="form-group">
          <label>Intro assets</label>
          <p className="muted" style={{ marginTop: "0.25rem" }}>
            Upload your own intro music and beginning clip. Default assets remain available.
          </p>
          <div className="asset-row">
            <div className="asset-row-header">
              <span>Start music</span>
              <input
                type="file"
                accept=".wav,audio/wav"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  setUploadingAsset("start_music");
                  setAssetError(null);
                  try {
                    await uploadAsset("start_music", file);
                    await onUpdate({});
                  } catch (err) {
                    setAssetError(
                      err instanceof Error ? err.message : "Failed to upload asset"
                    );
                  } finally {
                    setUploadingAsset(null);
                    e.currentTarget.value = "";
                  }
                }}
              />
            </div>
            <select
              value={assetSelections.start_music ?? "default"}
              onChange={(e) =>
                setAssetSelections((prev) => ({
                  ...prev,
                  start_music: e.target.value,
                }))
              }
            >
              {(settings.asset_options?.start_music ?? []).map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div className="asset-row">
            <div className="asset-row-header">
              <span>Beginning</span>
              <input
                type="file"
                accept=".wav,audio/wav"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  setUploadingAsset("beginning");
                  setAssetError(null);
                  try {
                    await uploadAsset("beginning", file);
                    await onUpdate({});
                  } catch (err) {
                    setAssetError(
                      err instanceof Error ? err.message : "Failed to upload asset"
                    );
                  } finally {
                    setUploadingAsset(null);
                    e.currentTarget.value = "";
                  }
                }}
              />
            </div>
            <select
              value={assetSelections.beginning ?? "default"}
              onChange={(e) =>
                setAssetSelections((prev) => ({
                  ...prev,
                  beginning: e.target.value,
                }))
              }
            >
              {(settings.asset_options?.beginning ?? []).map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          {uploadingAsset && (
            <p className="muted" style={{ marginTop: "0.5rem" }}>
              Uploading…
            </p>
          )}
          {assetError && (
            <p className="muted" style={{ marginTop: "0.5rem" }}>
              {assetError}
            </p>
          )}
        </div>
        <div className="form-group">
          <label htmlFor="tag-input">Tags</label>
          <div className="tag-input-row">
            <input
              id="tag-input"
              type="text"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              placeholder="Add tag"
            />
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                const next = tagInput.trim();
                if (!next || tags.includes(next)) return;
                setTags((prev) => [...prev, next]);
                setTagInput("");
              }}
            >
              Add
            </button>
          </div>
          {tags.length === 0 ? (
            <p className="muted" style={{ marginTop: "0.5rem" }}>
              No tags yet. Add some to categorize completed pipelines.
            </p>
          ) : (
            <div className="tag-list">
              {tags.map((tag) => (
                <span key={tag} className="tag-chip">
                  {tag}
                  <button
                    type="button"
                    className="tag-remove"
                    onClick={() =>
                      setTags((prev) => prev.filter((item) => item !== tag))
                    }
                    aria-label={`Remove tag ${tag}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
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
