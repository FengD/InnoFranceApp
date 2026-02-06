import { useState } from "react";
import { uploadAudio } from "../api";
import type { PipelineStartRequest } from "../types";

type SourceType = "youtube" | "audio_url" | "audio_path";

interface PipelineFormProps {
  onStart: (body: PipelineStartRequest) => Promise<void>;
  disabled: boolean;
  maxQueued: number;
  providerAvailability?: Record<string, boolean>;
}

export function PipelineForm({
  onStart,
  disabled,
  maxQueued,
  providerAvailability = {},
}: PipelineFormProps) {
  const [sourceType, setSourceType] = useState<SourceType>("youtube");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [audioUrl, setAudioUrl] = useState("");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [provider, setProvider] = useState("openai");
  const [modelName, setModelName] = useState("");
  const [language, setLanguage] = useState("fr");
  const [chunkLength, setChunkLength] = useState(30);
  const [speed, setSpeed] = useState(1.0);
  const [manualSpeakers, setManualSpeakers] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body: PipelineStartRequest = {
        provider,
        model_name: modelName.trim(),
        language,
        chunk_length: chunkLength,
        speed,
        manual_speakers: manualSpeakers,
      };
      if (!body.model_name) return;
      if (sourceType === "youtube") {
        if (!youtubeUrl.trim()) return;
        body.youtube_url = youtubeUrl.trim();
      } else if (sourceType === "audio_url") {
        if (!audioUrl.trim()) return;
        body.audio_url = audioUrl.trim();
      } else {
        if (!audioFile) return;
        setUploading(true);
        const uploaded = await uploadAudio(audioFile);
        body.audio_path = uploaded.path;
      }
      await onStart(body);
      setYoutubeUrl("");
      setAudioUrl("");
      setAudioFile(null);
    } finally {
      setUploading(false);
      setSubmitting(false);
    }
  };

  const canSubmit =
    (sourceType === "youtube" && youtubeUrl.trim()) ||
    (sourceType === "audio_url" && audioUrl.trim()) ||
    (sourceType === "audio_path" && audioFile);

  const hasModelName = modelName.trim().length > 0;

  return (
    <form className="form" onSubmit={handleSubmit}>
      <div className="form-group">
        <label>Source</label>
        <select
          value={sourceType}
          onChange={(e) => setSourceType(e.target.value as SourceType)}
        >
          <option value="youtube">YouTube URL</option>
          <option value="audio_url">Audio URL</option>
          <option value="audio_path">Local audio path</option>
        </select>
      </div>
      {sourceType === "youtube" && (
        <div className="form-group">
          <label htmlFor="youtube-url">YouTube URL</label>
          <input
            id="youtube-url"
            type="url"
            value={youtubeUrl}
            onChange={(e) => setYoutubeUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
          />
        </div>
      )}
      {sourceType === "audio_url" && (
        <div className="form-group">
          <label htmlFor="audio-url">Audio URL</label>
          <input
            id="audio-url"
            type="url"
            value={audioUrl}
            onChange={(e) => setAudioUrl(e.target.value)}
            placeholder="https://example.com/audio.mp3"
          />
        </div>
      )}
      {sourceType === "audio_path" && (
        <div className="form-group">
          <label htmlFor="audio-file">Local audio file</label>
          <input
            id="audio-file"
            type="file"
            accept=".mp3,.wav,audio/mpeg,audio/wav"
            onChange={(e) => setAudioFile(e.target.files?.[0] ?? null)}
          />
          {audioFile && (
            <span className="muted">Selected: {audioFile.name}</span>
          )}
        </div>
      )}
      <div className="form-row">
        <div className="form-group">
          <label htmlFor="provider">Provider</label>
          <select
            id="provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            {[
              { key: "openai", label: "OpenAI", needsKey: true },
              { key: "deepseek", label: "DeepSeek", needsKey: true },
              { key: "qwen", label: "Qwen", needsKey: true },
              { key: "glm", label: "GLM", needsKey: true },
              { key: "ollama", label: "Ollama", needsKey: false },
              { key: "sglang", label: "SGLang", needsKey: false },
              { key: "vllm", label: "vLLM", needsKey: false },
            ].map((providerItem) => {
              const available =
                providerAvailability[providerItem.key] ?? !providerItem.needsKey;
              const label = available
                ? providerItem.label
                : `${providerItem.label} (API key required)`;
              return (
                <option
                  key={providerItem.key}
                  value={providerItem.key}
                  disabled={!available}
                >
                  {label}
                </option>
              );
            })}
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="model-name">Model name</label>
          <input
            id="model-name"
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            placeholder="gpt-4o-mini, deepseek-chat, ..."
          />
        </div>
        <div className="form-group">
          <label htmlFor="language">Language</label>
          <select
            id="language"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
          >
            <option value="fr">French</option>
            <option value="en">English</option>
            <option value="de">German</option>
            <option value="it">Italian</option>
            <option value="es">Spanish</option>
            <option value="ja">Japanese</option>
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="chunk-length">Chunk length</label>
          <input
            id="chunk-length"
            type="number"
            min={10}
            max={120}
            value={chunkLength}
            onChange={(e) => setChunkLength(Number(e.target.value))}
          />
        </div>
        <div className="form-group">
          <label htmlFor="speed">Speed</label>
          <input
            id="speed"
            type="number"
            min={0.5}
            max={2}
            step={0.1}
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
          />
        </div>
      </div>
      <div className="form-actions">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={
            disabled || !canSubmit || !hasModelName || submitting || uploading
          }
        >
          {uploading ? "Uploading…" : submitting ? "Starting…" : "Start pipeline"}
        </button>
        {disabled && (
          <span className="muted">
            Queue full (max {maxQueued} pipelines).
          </span>
        )}
        {!hasModelName && (
          <span className="muted">Model name is required.</span>
        )}
      </div>
      <div className="form-group">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={manualSpeakers}
            onChange={(e) => setManualSpeakers(e.target.checked)}
          />
          Provide speaker JSON after translation
        </label>
        <p className="muted" style={{ marginTop: "0.25rem", marginBottom: 0 }}>
          If enabled, the pipeline pauses after translation and waits for your
          speaker configs before voice synthesis.
        </p>
      </div>
    </form>
  );
}
