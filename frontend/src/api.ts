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
}): Promise<SettingsResponse> {
  return request("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function listJobs(): Promise<PipelineListResponse> {
  return request("/api/pipeline/jobs");
}

export async function getJob(jobId: string): Promise<PipelineJob> {
  return request(`/api/pipeline/jobs/${jobId}`);
}

export async function startPipeline(
  body: PipelineStartRequest
): Promise<PipelineJob> {
  return request("/api/pipeline/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
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
