import { useState } from "react";
import type { PipelineStartRequest } from "../types";

type SourceType = "youtube" | "audio_url" | "audio_path";

interface PipelineFormProps {
  onStart: (body: PipelineStartRequest) => Promise<void>;
  disabled: boolean;
  maxQueued: number;
}

export function PipelineForm({
  onStart,
  disabled,
  maxQueued,
}: PipelineFormProps) {
  const [sourceType, setSourceType] = useState<SourceType>("youtube");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [audioUrl, setAudioUrl] = useState("");
  const [audioPath, setAudioPath] = useState("");
  const [provider, setProvider] = useState("openai");
  const [language, setLanguage] = useState("fr");
  const [chunkLength, setChunkLength] = useState(30);
  const [speed, setSpeed] = useState(1.0);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body: PipelineStartRequest = {
        provider,
        language,
        chunk_length: chunkLength,
        speed,
      };
      if (sourceType === "youtube") {
        if (!youtubeUrl.trim()) return;
        body.youtube_url = youtubeUrl.trim();
      } else if (sourceType === "audio_url") {
        if (!audioUrl.trim()) return;
        body.audio_url = audioUrl.trim();
      } else {
        if (!audioPath.trim()) return;
        body.audio_path = audioPath.trim();
      }
      await onStart(body);
      setYoutubeUrl("");
      setAudioUrl("");
      setAudioPath("");
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit =
    (sourceType === "youtube" && youtubeUrl.trim()) ||
    (sourceType === "audio_url" && audioUrl.trim()) ||
    (sourceType === "audio_path" && audioPath.trim());

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
          <label htmlFor="audio-path">Local path</label>
          <input
            id="audio-path"
            type="text"
            value={audioPath}
            onChange={(e) => setAudioPath(e.target.value)}
            placeholder="/path/to/audio.mp3"
          />
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
            <option value="openai">OpenAI</option>
            <option value="deepseek">DeepSeek</option>
          </select>
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
          disabled={disabled || !canSubmit || submitting}
        >
          {submitting ? "Starting…" : "Start pipeline"}
        </button>
        {disabled && (
          <span className="muted">
            Queue full (max {maxQueued} pipelines).
          </span>
        )}
      </div>
    </form>
  );
}
