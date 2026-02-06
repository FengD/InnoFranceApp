import type {
  PipelineJob,
  PipelineListResponse,
  PipelineStartRequest,
  SettingsResponse,
} from "./types";

const API_BASE = "";

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? "Request failed");
  }
  return res.json() as Promise<T>;
}

export async function getSettings(): Promise<SettingsResponse> {
  return request("/api/settings");
}

export async function updateSettings(body: {
  parallel_enabled?: boolean;
  max_concurrent?: number;
  tags?: string[];
}): Promise<SettingsResponse> {
  return request("/api/settings", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listJobs(
  includeSteps = false
): Promise<PipelineListResponse> {
  const query = includeSteps ? "?include_steps=true" : "";
  return request(`/api/pipeline/jobs${query}`);
}

export async function getJob(jobId: string): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}`);
}

export async function deleteJob(jobId: string): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}`, {
    method: "DELETE",
  });
}

export async function reorderQueue(jobIds: string[]): Promise<PipelineListResponse> {
  return request("/api/pipeline/queue/reorder", {
    method: "POST",
    body: JSON.stringify({ job_ids: jobIds }),
  });
}

export async function updateJobMetadata(
  jobId: string,
  body: {
    note?: string | null;
    custom_name?: string | null;
    tags?: string[];
    published?: boolean;
  }
): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}/metadata`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}


export async function submitSpeakers(
  jobId: string,
  speakersJson: string
): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}/speakers`, {
    method: "POST",
    body: JSON.stringify({ speakers_json: speakersJson }),
  });
}

export async function getJobSpeakersTemplate(
  jobId: string
): Promise<{ speakers: unknown[]; detected_speakers: string[] }> {
  const res = await request<{ speakers: unknown[]; detected_speakers: string[] }>(
    `/api/pipeline/jobs/${jobId}/speakers-template`
  );
  return res;
}

export async function regenerateJobAudio(
  jobId: string,
  speakersJson: string
): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}/tts`, {
    method: "POST",
    body: JSON.stringify({ speakers_json: speakersJson }),
  });
}

export async function getJobSummary(jobId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/pipeline/jobs/${jobId}/summary`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? "Request failed");
  }
  return res.text();
}

export async function getJobTranslation(jobId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/pipeline/jobs/${jobId}/translated`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? "Request failed");
  }
  return res.text();
}

export async function updateJobSummary(
  jobId: string,
  text: string
): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}/summary`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function updateJobTranslation(
  jobId: string,
  text: string
): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}/translated`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function generateSummaryAudio(
  jobId: string
): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}/summary-audio`, {
    method: "POST",
  });
}

export async function mergeFinalAudio(jobId: string): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}/merge-audio`, {
    method: "POST",
  });
}

export async function startPipeline(
  body: PipelineStartRequest
): Promise<PipelineJob> {
  return request("/api/pipeline/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function uploadAudio(file: File): Promise<{ path: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/uploads/audio`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? "Upload failed");
  }
  return res.json() as Promise<{ path: string }>;
}

export function streamJobEvents(
  jobId: string,
  onEvent: (event: string, data: unknown) => void
): () => void {
  const url = `${API_BASE}/api/pipeline/jobs/${jobId}/stream`;
  const es = new EventSource(url);
  es.addEventListener("progress", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data);
      onEvent("progress", data);
    } catch {
      onEvent("progress", e.data);
    }
  });
  es.addEventListener("done", () => {
    onEvent("done", null);
    es.close();
  });
  es.onerror = () => {
    es.close();
  };
  return () => es.close();
}

export function downloadUrl(path: string): string {
  return `${API_BASE}/api/artifacts/download?path=${encodeURIComponent(path)}`;
}

export function previewSummaryUrl(path: string): string {
  return `${API_BASE}/api/artifacts/preview/summary?path=${encodeURIComponent(path)}`;
}

export function previewAudioUrl(path: string): string {
  return `${API_BASE}/api/artifacts/preview/audio?path=${encodeURIComponent(path)}`;
}

export function exportJobUrl(jobId: string): string {
  return `${API_BASE}/api/pipeline/jobs/${jobId}/export`;
}
