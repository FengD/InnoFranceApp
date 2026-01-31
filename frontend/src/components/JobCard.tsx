import { useEffect, useMemo, useState } from "react";
import {
  downloadUrl,
  generateSummaryAudio,
  getJobSummary,
  mergeFinalAudio,
  previewAudioUrl,
  submitSpeakers,
  updateJobSummary,
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
  onDelete?: () => void;
}

export function JobCard({ job, onRefresh, onDelete }: JobCardProps) {
  const [showDetails, setShowDetails] = useState(false);
  const [previewSummary, setPreviewSummary] = useState(false);
  const [previewAudio, setPreviewAudio] = useState(false);
  const [summaryText, setSummaryText] = useState("");
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summarySaving, setSummarySaving] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryDirty, setSummaryDirty] = useState(false);
  const [speakerJson, setSpeakerJson] = useState("");
  const [speakerSubmitting, setSpeakerSubmitting] = useState(false);
  const [speakerError, setSpeakerError] = useState<string | null>(null);
  const [summaryAudioBusy, setSummaryAudioBusy] = useState(false);
  const [mergeBusy, setMergeBusy] = useState(false);

  const stepMap = useMemo(() => {
    const map = new Map<string, typeof job.steps[number]>();
    job.steps.forEach((step) => {
      map.set(step.step, step);
    });
    return map;
  }, [job.steps]);

  const completedCount = Array.from(stepMap.values()).filter(
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
  const summaryAudioRelative = result?.summary_audio_relative;
  const mergedAudioRelative = result?.merged_audio_relative;
  const summaryUrl = result?.summary_url;
  const audioUrl = result?.audio_url;
  const summaryAudioUrl = result?.summary_audio_url;
  const mergedAudioUrl = result?.merged_audio_url;

  const waitingSpeakers =
    stepMap.get("speakers")?.status === "waiting" ||
    (job.speaker_required && !job.speaker_submitted);

  useEffect(() => {
    if (!previewSummary || !job.job_id) {
      return;
    }
    setSummaryLoading(true);
    setSummaryError(null);
    getJobSummary(job.job_id)
      .then((text) => {
        setSummaryText(text);
        setSummaryDirty(false);
      })
      .catch((err) => {
        setSummaryError(err instanceof Error ? err.message : "Failed to load summary");
      })
      .finally(() => setSummaryLoading(false));
  }, [previewSummary, job.job_id]);

  const handleSummarySave = async () => {
    setSummarySaving(true);
    setSummaryError(null);
    try {
      await updateJobSummary(job.job_id, summaryText);
      setSummaryDirty(false);
      onRefresh();
    } catch (err) {
      setSummaryError(err instanceof Error ? err.message : "Failed to save summary");
    } finally {
      setSummarySaving(false);
    }
  };

  const handleSpeakerSubmit = async () => {
    if (!speakerJson.trim()) return;
    setSpeakerSubmitting(true);
    setSpeakerError(null);
    try {
      await submitSpeakers(job.job_id, speakerJson);
      setSpeakerJson("");
      onRefresh();
    } catch (err) {
      setSpeakerError(err instanceof Error ? err.message : "Failed to submit speakers");
    } finally {
      setSpeakerSubmitting(false);
    }
  };

  const handleSummaryAudio = async () => {
    setSummaryAudioBusy(true);
    try {
      await generateSummaryAudio(job.job_id);
      onRefresh();
    } finally {
      setSummaryAudioBusy(false);
    }
  };

  const handleMergeAudio = async () => {
    setMergeBusy(true);
    try {
      await mergeFinalAudio(job.job_id);
      onRefresh();
    } finally {
      setMergeBusy(false);
    }
  };

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
        {onDelete && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onDelete}
          >
            Delete
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
          onClick={() => {
            setShowDetails((v) => {
              const next = !v;
              if (next && job.steps.length === 0) {
                onRefresh();
              }
              return next;
            });
          }}
          aria-expanded={showDetails}
        >
          {showDetails ? "Hide details" : "Show details"}
        </button>
      </div>

      {showDetails && (
        <div className="job-steps">
          {STEP_ORDER.map((stepKey) => {
            const step = stepMap.get(stepKey);
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
          {waitingSpeakers && (
            <div className="job-step job-step--waiting">
              <span className="job-step-label">Speakers input</span>
              <span className="job-step-status">waiting</span>
              <span className="job-step-message">
                Paste speaker JSON to continue voice synthesis.
              </span>
              <textarea
                className="job-step-textarea"
                value={speakerJson}
                onChange={(e) => setSpeakerJson(e.target.value)}
                placeholder='[{"speaker_tag":"[SPEAKER0]","ref_audio":"...","ref_text":"...","language":"Chinese"}]'
              />
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSpeakerSubmit}
                disabled={speakerSubmitting || !speakerJson.trim()}
              >
                {speakerSubmitting ? "Submitting…" : "Submit speakers"}
              </button>
              {speakerError && <span className="job-step-error">{speakerError}</span>}
            </div>
          )}
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
              {summaryRelative ? (
                <a
                  href={downloadUrl(summaryRelative)}
                  download
                  target="_blank"
                  rel="noreferrer"
                >
                  Download
                </a>
              ) : (
                <span className="muted">Missing summary</span>
              )}
              {summaryUrl && (
                <a href={summaryUrl} target="_blank" rel="noreferrer">
                  Open S3
                </a>
              )}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPreviewSummary((v) => !v)}
              >
                {previewSummary ? "Hide preview" : "Preview"}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={handleSummaryAudio}
                disabled={summaryAudioBusy}
              >
                {summaryAudioBusy ? "Generating…" : "Generate summary audio"}
              </button>
            </div>
            {previewSummary && (
              <div className="artifact-preview">
                {summaryLoading ? (
                  <p className="muted">Loading summary…</p>
                ) : (
                  <>
                    <textarea
                      className="preview-textarea"
                      value={summaryText}
                      onChange={(e) => {
                        setSummaryText(e.target.value);
                        setSummaryDirty(true);
                      }}
                    />
                    <div className="artifact-actions">
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={handleSummarySave}
                        disabled={summarySaving || !summaryDirty}
                      >
                        {summarySaving ? "Saving…" : "Save summary"}
                      </button>
                      {summaryError && (
                        <span className="muted">{summaryError}</span>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
            <div className="artifact-row">
              <span>Audio</span>
              {audioRelative ? (
                <a
                  href={downloadUrl(audioRelative)}
                  download
                  target="_blank"
                  rel="noreferrer"
                >
                  Download
                </a>
              ) : (
                <span className="muted">Missing audio</span>
              )}
              {audioUrl && (
                <a href={audioUrl} target="_blank" rel="noreferrer">
                  Open S3
                </a>
              )}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPreviewAudio((v) => !v)}
                disabled={!audioRelative}
              >
                {previewAudio ? "Hide preview" : "Preview"}
              </button>
            </div>
            {previewAudio && (
              <div className="artifact-preview">
                {audioRelative ? (
                  <audio
                    controls
                    src={previewAudioUrl(audioRelative)}
                    className="preview-audio"
                  >
                    Your browser does not support audio.
                  </audio>
                ) : (
                  <span className="muted">Missing audio file</span>
                )}
              </div>
            )}
            <div className="artifact-row">
              <span>Summary audio</span>
              {summaryAudioRelative ? (
                <>
                  <a
                    href={downloadUrl(summaryAudioRelative)}
                    download
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download
                  </a>
                  {summaryAudioUrl && (
                    <a href={summaryAudioUrl} target="_blank" rel="noreferrer">
                      Open S3
                    </a>
                  )}
                  <audio
                    controls
                    src={previewAudioUrl(summaryAudioRelative)}
                    className="preview-audio"
                  >
                    Your browser does not support audio.
                  </audio>
                </>
              ) : (
                <span className="muted">Not generated yet</span>
              )}
            </div>
            <div className="artifact-row">
              <span>Final audio</span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={handleMergeAudio}
                disabled={mergeBusy || !summaryAudioRelative}
              >
                {mergeBusy ? "Merging…" : "Merge final audio"}
              </button>
              {mergedAudioRelative ? (
                <>
                  <a
                    href={downloadUrl(mergedAudioRelative)}
                    download
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download
                  </a>
                  {mergedAudioUrl && (
                    <a href={mergedAudioUrl} target="_blank" rel="noreferrer">
                      Open S3
                    </a>
                  )}
                  <audio
                    controls
                    src={previewAudioUrl(mergedAudioRelative)}
                    className="preview-audio"
                  >
                    Your browser does not support audio.
                  </audio>
                </>
              ) : (
                <span className="muted">Not merged yet</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
