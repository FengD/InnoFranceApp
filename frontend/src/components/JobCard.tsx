import { useState } from "react";
import {
  downloadUrl,
  previewAudioUrl,
  previewSummaryUrl,
} from "../api";
import type { PipelineJob } from "../types";

const STEP_ORDER = [
  "youtube_audio",
  "asr",
  "translate",
  "summary",
  "speakers",
  "tts",
];

interface JobCardProps {
  job: PipelineJob;
  onRefresh: () => void;
}

export function JobCard({ job, onRefresh }: JobCardProps) {
  const [showDetails, setShowDetails] = useState(false);
  const [previewSummary, setPreviewSummary] = useState(false);
  const [previewAudio, setPreviewAudio] = useState(false);

  const stepsWithOrder = [...job.steps].sort(
    (a, b) => STEP_ORDER.indexOf(a.step) - STEP_ORDER.indexOf(b.step)
  );
  const completedCount = job.steps.filter(
    (s) => s.status === "completed"
  ).length;
  const progressPercent =
    job.status === "completed" || job.status === "failed"
      ? job.status === "completed"
        ? 100
        : Math.min(100, (completedCount / STEP_ORDER.length) * 100)
      : (completedCount / STEP_ORDER.length) * 100;

  const statusLabel =
    job.status === "queued"
      ? "Queued"
      : job.status === "running"
        ? "Running"
        : job.status === "completed"
          ? "Completed"
          : "Failed";

  const result = job.result;
  const summaryRelative = result?.summary_relative ?? result?.summary_name;
  const audioRelative = result?.audio_relative ?? result?.audio_name;

  return (
    <div className={`job-card job-card--${job.status}`}>
      <div className="job-card-header">
        <div className="job-card-meta">
          <span className="job-id" title={job.job_id}>
            {job.job_id.slice(0, 8)}
          </span>
          <span className={`job-status job-status--${job.status}`}>
            {statusLabel}
          </span>
          <span className="job-date">
            {new Date(job.created_at).toLocaleString()}
          </span>
        </div>
        {(job.status === "running" || job.status === "queued") && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onRefresh}
          >
            Refresh
          </button>
        )}
      </div>

      {(job.status === "running" || job.status === "completed") && (
        <div className="job-progress">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <span className="progress-label">
            {completedCount} / {STEP_ORDER.length} steps
          </span>
        </div>
      )}

      <div className="job-details-toggle">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setShowDetails((v) => !v)}
          aria-expanded={showDetails}
        >
          {showDetails ? "Hide details" : "Show details"}
        </button>
      </div>

      {showDetails && (
        <div className="job-steps">
          {STEP_ORDER.map((stepKey) => {
            const step = job.steps.find((s) => s.step === stepKey);
            const label =
              stepKey === "youtube_audio"
                ? "Audio source"
                : stepKey === "asr"
                  ? "Transcription"
                  : stepKey === "translate"
                    ? "Translation"
                    : stepKey === "summary"
                      ? "Summary"
                      : stepKey === "speakers"
                        ? "Speakers"
                        : "TTS";
            return (
              <div
                key={stepKey}
                className={`job-step job-step--${step?.status ?? "pending"}`}
              >
                <span className="job-step-label">{label}</span>
                <span className="job-step-status">
                  {step?.status ?? "pending"}
                </span>
                {step?.message && (
                  <span className="job-step-message">{step.message}</span>
                )}
                {step?.detail && (
                  <pre className="job-step-detail">{step.detail}</pre>
                )}
              </div>
            );
          })}
          {job.error && (
            <div className="job-error" role="alert">
              {job.error}
            </div>
          )}
        </div>
      )}

      {job.status === "completed" && result && (
        <div className="job-artifacts">
          <h4>Outputs</h4>
          <div className="artifact-links">
            <div className="artifact-row">
              <span>Summary</span>
              <a
                href={downloadUrl(summaryRelative)}
                download
                target="_blank"
                rel="noreferrer"
              >
                Download
              </a>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPreviewSummary((v) => !v)}
              >
                {previewSummary ? "Hide preview" : "Preview"}
              </button>
            </div>
            {previewSummary && (
              <div className="artifact-preview">
                <iframe
                  title="Summary preview"
                  src={previewSummaryUrl(summaryRelative)}
                  className="preview-iframe preview-text"
                />
              </div>
            )}
            <div className="artifact-row">
              <span>Audio</span>
              <a
                href={downloadUrl(audioRelative)}
                download
                target="_blank"
                rel="noreferrer"
              >
                Download
              </a>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPreviewAudio((v) => !v)}
              >
                {previewAudio ? "Hide preview" : "Preview"}
              </button>
            </div>
            {previewAudio && (
              <div className="artifact-preview">
                <audio
                  controls
                  src={previewAudioUrl(audioRelative)}
                  className="preview-audio"
                >
                  Your browser does not support audio.
                </audio>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
