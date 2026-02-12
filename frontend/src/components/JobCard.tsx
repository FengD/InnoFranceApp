import { useCallback, useEffect, useMemo, useState } from "react";
import {
  downloadUrl,
  exportJobUrl,
  generateSummaryAudio,
  getJobSpeakersTemplate,
  getJobPolish,
  getJobSummary,
  mergeFinalAudio,
  previewAudioUrl,
  regenerateJobAudio,
  submitSpeakers,
  updateJobPolish,
  updateJobSummary,
} from "../api";
import type { PipelineJob } from "../types";

const STEP_ORDER = [
  "youtube_audio",
  "asr",
  "translate",
  "polish",
  "summary",
  "speakers",
  "tts",
];

interface JobCardProps {
  job: PipelineJob;
  onRefresh: () => void;
  onDelete?: () => void;
  availableTags?: string[];
  onUpdateMeta?: (patch: {
    note?: string | null;
    custom_name?: string | null;
    tags?: string[];
    published?: boolean;
  }) => Promise<void>;
}

export function JobCard({
  job,
  onRefresh,
  onDelete,
  availableTags = [],
  onUpdateMeta,
}: JobCardProps) {
  const [showDetails, setShowDetails] = useState(false);
  const [outputsOpen, setOutputsOpen] = useState(false);
  const [previewSummary, setPreviewSummary] = useState(false);
  const [previewAudio, setPreviewAudio] = useState(false);
  const [summaryText, setSummaryText] = useState("");
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summarySaving, setSummarySaving] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryDirty, setSummaryDirty] = useState(false);
  const [previewPolish, setPreviewPolish] = useState(false);
  const [polishText, setPolishText] = useState("");
  const [polishLoading, setPolishLoading] = useState(false);
  const [polishSaving, setPolishSaving] = useState(false);
  const [polishError, setPolishError] = useState<string | null>(null);
  const [polishDirty, setPolishDirty] = useState(false);
  const [speakerJson, setSpeakerJson] = useState("");
  const [speakerSubmitting, setSpeakerSubmitting] = useState(false);
  const [speakerError, setSpeakerError] = useState<string | null>(null);
  const [speakerTemplateLoading, setSpeakerTemplateLoading] = useState(false);
  const [speakerTemplateError, setSpeakerTemplateError] = useState<string | null>(null);
  const [speakerTemplateLoaded, setSpeakerTemplateLoaded] = useState(false);
  const [summaryAudioBusy, setSummaryAudioBusy] = useState(false);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [showRegenerate, setShowRegenerate] = useState(false);
  const [regenSpeakerJson, setRegenSpeakerJson] = useState("");
  const [regenBusy, setRegenBusy] = useState(false);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [showSpeakerClips, setShowSpeakerClips] = useState(false);
  const [clipNonce, setClipNonce] = useState(0);
  const [noteText, setNoteText] = useState(job.note ?? "");
  const [noteDirty, setNoteDirty] = useState(false);
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [nameInput, setNameInput] = useState(job.custom_name ?? "");
  const [tagSaving, setTagSaving] = useState(false);
  const [tagError, setTagError] = useState<string | null>(null);
  const [tagOpen, setTagOpen] = useState(false);
  const [publishedSaving, setPublishedSaving] = useState(false);
  const [publishedError, setPublishedError] = useState<string | null>(null);

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
  const speakerAudioRelatives = result?.speaker_audio_relatives ?? [];
  const speakerAudioUrls = result?.speaker_audio_urls ?? [];
  const summaryAudioUrl = result?.summary_audio_url;
  const mergedAudioUrl = result?.merged_audio_url;

  const waitingSpeakers =
    stepMap.get("speakers")?.status === "waiting" ||
    (job.speaker_required && !job.speaker_submitted);
  const canEditPolish =
    job.speaker_required &&
    (stepMap.get("polish")?.status === "completed" ||
      Boolean(result?.polished_path) ||
      Boolean(result?.polished_relative));

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

  useEffect(() => {
    if (!previewPolish || !job.job_id) {
      return;
    }
    setPolishLoading(true);
    setPolishError(null);
    getJobPolish(job.job_id)
      .then((text) => {
        setPolishText(text);
        setPolishDirty(false);
      })
      .catch((err) => {
        setPolishError(err instanceof Error ? err.message : "Failed to load polish");
      })
      .finally(() => setPolishLoading(false));
  }, [previewPolish, job.job_id]);

  useEffect(() => {
    setSpeakerTemplateLoaded(false);
  }, [job.job_id]);

  useEffect(() => {
    setOutputsOpen(false);
    setPreviewSummary(false);
    setPreviewAudio(false);
    setPreviewPolish(false);
    setShowRegenerate(false);
    setShowSpeakerClips(false);
    setNoteText(job.note ?? "");
    setNoteDirty(false);
    setNoteOpen(false);
    setTagOpen(false);
    setNameInput(job.custom_name ?? "");
    setClipNonce(0);
  }, [job.job_id]);

  useEffect(() => {
    setNoteText(job.note ?? "");
    setNoteDirty(false);
    setNameInput(job.custom_name ?? "");
  }, [job.note, job.custom_name]);

  const fetchSpeakerTemplate = useCallback(async () => {
    setSpeakerTemplateLoading(true);
    setSpeakerTemplateError(null);
    try {
      const template = await getJobSpeakersTemplate(job.job_id);
      return {
        text: JSON.stringify(template.speakers, null, 2),
        detected: template.detected_speakers ?? [],
      };
    } catch (err) {
      setSpeakerTemplateError(
        err instanceof Error ? err.message : "Failed to load speaker template"
      );
      return null;
    } finally {
      setSpeakerTemplateLoading(false);
    }
  }, [job.job_id]);

  useEffect(() => {
    if (!waitingSpeakers || speakerTemplateLoaded || speakerJson.trim()) {
      return;
    }
    fetchSpeakerTemplate().then((result) => {
      if (!result) return;
      if (result.detected.length === 0) {
        setSpeakerTemplateError("No detected speakers yet.");
        return;
      }
      setSpeakerJson(result.text);
      setSpeakerTemplateLoaded(true);
    });
  }, [fetchSpeakerTemplate, speakerJson, speakerTemplateLoaded, waitingSpeakers]);

  useEffect(() => {
    if (!showRegenerate || regenSpeakerJson.trim()) {
      return;
    }
    fetchSpeakerTemplate().then((result) => {
      if (!result) return;
      if (result.detected.length === 0) {
        setSpeakerTemplateError("No detected speakers yet.");
        return;
      }
      setRegenSpeakerJson(result.text);
    });
  }, [fetchSpeakerTemplate, regenSpeakerJson, showRegenerate]);

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

  const handlePolishSave = async () => {
    setPolishSaving(true);
    setPolishError(null);
    try {
      await updateJobPolish(job.job_id, polishText);
      setPolishDirty(false);
      onRefresh();
    } catch (err) {
      setPolishError(err instanceof Error ? err.message : "Failed to save polish");
    } finally {
      setPolishSaving(false);
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

  const handleLoadSpeakerTemplate = async (
    target: "speaker" | "regen" = "speaker"
  ) => {
    const result = await fetchSpeakerTemplate();
    if (!result) return;
    if (result.detected.length === 0) {
      setSpeakerTemplateError("No detected speakers yet.");
      return;
    }
    if (target === "speaker") {
      setSpeakerJson(result.text);
      setSpeakerTemplateLoaded(true);
    } else {
      setRegenSpeakerJson(result.text);
    }
  };

  const handleRegenerateAudio = async () => {
    if (!regenSpeakerJson.trim()) return;
    setRegenBusy(true);
    setRegenError(null);
    try {
      await regenerateJobAudio(job.job_id, regenSpeakerJson);
      onRefresh();
    } catch (err) {
      setRegenError(err instanceof Error ? err.message : "Failed to regenerate audio");
    } finally {
      setRegenBusy(false);
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


  const handleSaveNote = async () => {
    if (!onUpdateMeta) return;
    setNoteSaving(true);
    setNoteError(null);
    try {
      await onUpdateMeta({ note: noteText });
      setNoteDirty(false);
      setNoteOpen(false);
    } catch (err) {
      setNoteError(err instanceof Error ? err.message : "Failed to save note");
    } finally {
      setNoteSaving(false);
    }
  };

  const handleSaveName = async () => {
    if (!onUpdateMeta) return;
    try {
      await onUpdateMeta({ custom_name: nameInput });
      setRenameOpen(false);
    } catch {
      // ignore, error handled at parent
    }
  };

  const handleToggleTag = async (tag: string) => {
    if (!onUpdateMeta) return;
    const current = new Set(job.tags ?? []);
    if (current.has(tag)) {
      current.delete(tag);
    } else {
      current.add(tag);
    }
    setTagSaving(true);
    setTagError(null);
    try {
      await onUpdateMeta({ tags: Array.from(current) });
    } catch (err) {
      setTagError(err instanceof Error ? err.message : "Failed to update tags");
    } finally {
      setTagSaving(false);
    }
  };

  const handleTogglePublished = async () => {
    if (!onUpdateMeta) return;
    setPublishedSaving(true);
    setPublishedError(null);
    try {
      await onUpdateMeta({ published: !job.published });
    } catch (err) {
      setPublishedError(err instanceof Error ? err.message : "Failed to update");
    } finally {
      setPublishedSaving(false);
    }
  };

  return (
    <div className={`job-card job-card--${job.status}`}>
      <div className="job-card-header">
        <div className="job-card-meta">
          {job.status === "completed" && (
            <button
              type="button"
              className={`publish-toggle${job.published ? " is-published" : ""}`}
              onClick={handleTogglePublished}
              disabled={publishedSaving}
              title="Mark as published"
            >
              <span className="publish-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" role="img">
                  <path
                    d="M12 2l3 6 6 1-4.5 4.4 1 6.2L12 16l-5.5 3.6 1-6.2L3 9l6-1z"
                    fill="currentColor"
                  />
                </svg>
              </span>
            </button>
          )}
          <span className="job-id" title={job.job_id}>
            {job.job_id.slice(0, 8)}
          </span>
          <span className={`job-status job-status--${job.status}`}>
            {statusLabel}
          </span>
          <span className="job-date">
            {new Date(job.created_at).toLocaleString()}
          </span>
          {job.status === "completed" && (
            <>
              <span className="job-name">
                {job.custom_name?.trim() ? job.custom_name : "Unnamed"}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setRenameOpen(true)}
              >
                Rename
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setNoteOpen(true)}
              >
                Note
              </button>
              {availableTags.length > 0 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setTagOpen((v) => !v)}
                  aria-expanded={tagOpen}
                >
                  Tags
                </button>
              )}
            </>
          )}
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

      <div className="job-progress">
        {(job.status === "running" || job.status === "completed") && (
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        )}
        <div className="job-progress-row">
          <span className="progress-label">
            {completedCount} / {STEP_ORDER.length} steps
          </span>
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
                    : stepKey === "polish"
                      ? "Polish"
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
                  <pre className="job-step-detail">
                    {stripRunsPrefix(step.detail)}
                  </pre>
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
              {canEditPolish && (
                <div className="job-translation">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setPreviewPolish((v) => !v)}
                  >
                    {previewPolish ? "Hide polish" : "Preview polish"}
                  </button>
                  {previewPolish && (
                    <div className="artifact-preview">
                      {polishLoading ? (
                        <p className="muted">Loading polish…</p>
                      ) : (
                        <>
                          <textarea
                            className="preview-textarea"
                            value={polishText}
                            onChange={(e) => {
                              setPolishText(e.target.value);
                              setPolishDirty(true);
                            }}
                          />
                          <div className="artifact-actions">
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              onClick={handlePolishSave}
                              disabled={polishSaving || !polishDirty}
                            >
                              {polishSaving ? "Saving…" : "Save polish"}
                            </button>
                            {polishError && (
                              <span className="muted">{polishError}</span>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}
              <textarea
                className="job-step-textarea"
                value={speakerJson}
                onChange={(e) => setSpeakerJson(e.target.value)}
                placeholder='[{"speaker_tag":"[SPEAKER0]","ref_audio":"...","ref_text":"...","language":"Chinese"}]'
              />
              <div className="artifact-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => handleLoadSpeakerTemplate("speaker")}
                  disabled={speakerTemplateLoading}
                >
                  {speakerTemplateLoading ? "Loading…" : "Fill from detected speakers"}
                </button>
                {speakerTemplateError && (
                  <span className="muted">{speakerTemplateError}</span>
                )}
              </div>
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

      {job.status === "completed" && (
        <div className="job-meta">
          {tagOpen && availableTags.length > 0 && (
            <div className="job-meta-row">
              <span className="job-meta-label">Tags</span>
              <div className="tag-picker">
                {availableTags.map((tag) => {
                  const active = (job.tags ?? []).includes(tag);
                  return (
                    <button
                      key={tag}
                      type="button"
                      className={`tag-chip${active ? " is-active" : ""}`}
                      onClick={() => handleToggleTag(tag)}
                      disabled={tagSaving}
                    >
                      {tag}
                    </button>
                  );
                })}
              </div>
              {tagError && <span className="muted">{tagError}</span>}
            </div>
          )}
          {publishedError && (
            <div className="job-meta-row">
              <span className="muted">{publishedError}</span>
            </div>
          )}
        </div>
      )}

      {job.status === "completed" && result && (
        <div className="job-artifacts">
          <div className="job-artifacts-header">
            <h4>Outputs</h4>
            <div className="job-artifacts-actions">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setOutputsOpen((v) => !v)}
                aria-expanded={outputsOpen}
              >
                {outputsOpen ? "Collapse" : "Expand"}
              </button>
            </div>
          </div>
          {outputsOpen && (
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
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setShowRegenerate((v) => !v)}
              >
                {showRegenerate ? "Hide" : "Customize speakers"}
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
            {showRegenerate && (
              <div className="artifact-preview">
                <textarea
                  className="preview-textarea"
                  value={regenSpeakerJson}
                  onChange={(e) => setRegenSpeakerJson(e.target.value)}
                />
                <div className="artifact-actions">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={handleRegenerateAudio}
                    disabled={regenBusy || !regenSpeakerJson.trim()}
                  >
                    {regenBusy ? "Regenerating…" : "Regenerate audio"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => handleLoadSpeakerTemplate("regen")}
                    disabled={speakerTemplateLoading}
                  >
                    {speakerTemplateLoading ? "Loading…" : "Use detected speakers"}
                  </button>
                  {regenError && <span className="muted">{regenError}</span>}
                  {speakerTemplateError && (
                    <span className="muted">{speakerTemplateError}</span>
                  )}
                </div>
              </div>
            )}
            <div className="artifact-row">
              <span>Speaker clips</span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setShowSpeakerClips((v) => !v)}
                disabled={speakerAudioRelatives.length === 0}
              >
                {showSpeakerClips ? "Hide" : "Preview"}
              </button>
            </div>
            {showSpeakerClips && (
              <div className="artifact-preview">
                {speakerAudioRelatives.length === 0 ? (
                  <p className="muted">No speaker clips available.</p>
                ) : (
                  <div className="speaker-clips">
                    {speakerAudioRelatives.map((path, index) => {
                      const s3Url = speakerAudioUrls[index];
                      const tag =
                        result?.speaker_audio_tags?.[index] ?? `SPEAKER${index}`;
                      const segment = result?.speaker_clip_segments?.[tag];
                      const segmentLabel = segment
                        ? `${formatSeconds(segment.start)}–${formatSeconds(segment.end)}`
                        : null;
                      return (
                        <div key={path} className="speaker-clip">
                          <div className="speaker-clip-header">
                            <span>
                              {tag.toLowerCase()}.wav
                              {segmentLabel ? ` (${segmentLabel})` : ""}
                            </span>
                            <div className="speaker-clip-actions">
                              <a
                                href={withNonce(downloadUrl(path), clipNonce)}
                                download
                                target="_blank"
                                rel="noreferrer"
                              >
                                Download
                              </a>
                              {s3Url && (
                                <a href={s3Url} target="_blank" rel="noreferrer">
                                  Open S3
                                </a>
                              )}
                            </div>
                          </div>
                          <audio
                            controls
                            src={withNonce(previewAudioUrl(path), clipNonce)}
                            className="preview-audio"
                          >
                            Your browser does not support audio.
                          </audio>
                        </div>
                      );
                    })}
                  </div>
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
              {mergedAudioRelative && (
                <a
                  href={exportJobUrl(job.job_id)}
                  className="btn btn-ghost btn-sm"
                  download
                >
                  Export zip
                </a>
              )}
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
          )}
        </div>
      )}

      {renameOpen && (
        <div className="rename-modal" role="dialog" aria-label="Rename pipeline">
          <div className="rename-modal-inner">
            <h4>Rename pipeline</h4>
            <input
              type="text"
              className="modal-input"
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              placeholder="Custom name"
            />
            <p className="muted">
              Used for export zip filename (lowercase, spaces become underscores).
            </p>
            <div className="rename-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSaveName}
              >
                Save
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setRenameOpen(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {noteOpen && (
        <div className="rename-modal" role="dialog" aria-label="Edit note">
          <div className="rename-modal-inner">
            <h4>Note</h4>
            <textarea
              className="modal-input modal-textarea"
              value={noteText}
              onChange={(e) => {
                setNoteText(e.target.value);
                setNoteDirty(true);
              }}
              placeholder="Add a note to recognize this pipeline"
            />
            <div className="rename-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSaveNote}
                disabled={noteSaving || !noteDirty}
              >
                {noteSaving ? "Saving…" : "Save note"}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setNoteOpen(false)}
              >
                Close
              </button>
              {noteError && <span className="muted">{noteError}</span>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function stripRunsPrefix(detail: string): string {
  return detail
    .split("\n")
    .map((line) => {
      const unix = line.indexOf("/runs/");
      if (unix !== -1) {
        return line.slice(unix + "/runs/".length);
      }
      const win = line.indexOf("\\runs\\");
      if (win !== -1) {
        return line.slice(win + "\\runs\\".length);
      }
      return line;
    })
    .join("\n");
}

function withNonce(url: string, nonce: number): string {
  if (!nonce) return url;
  const joiner = url.includes("?") ? "&" : "?";
  return `${url}${joiner}v=${nonce}`;
}

function formatSeconds(value: number): string {
  if (!Number.isFinite(value)) return "";
  const total = Math.max(0, Math.floor(value));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
