export interface StepEvent {
  step: string;
  status: string;
  message: string;
  detail: string | null;
  timestamp: string;
}

export interface PipelineResult {
  summary_path: string;
  audio_path: string;
  run_dir: string;
  speakers_path?: string;
  summary_name: string;
  audio_name: string;
  summary_relative: string;
  audio_relative: string;
  speakers_relative?: string;
  summary_url?: string;
  audio_url?: string;
  speakers_url?: string;
  summary_audio_path?: string;
  summary_audio_relative?: string;
  summary_audio_url?: string;
  merged_audio_path?: string;
  merged_audio_relative?: string;
  merged_audio_url?: string;
}

export interface PipelineJob {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  steps: StepEvent[];
  result: PipelineResult | null;
  speaker_required?: boolean;
  speaker_submitted?: boolean;
}

export interface PipelineListResponse {
  jobs: PipelineJob[];
  max_concurrent: number;
  parallel_enabled: boolean;
}

export interface SettingsResponse {
  parallel_enabled: boolean;
  max_concurrent: number;
  max_queued: number;
}

export interface PipelineStartRequest {
  youtube_url?: string | null;
  audio_url?: string | null;
  audio_path?: string | null;
  provider?: string;
  model_name?: string | null;
  language?: string;
  chunk_length?: number;
  speed?: number;
  yt_cookies_file?: string | null;
  yt_cookies_from_browser?: string | null;
  yt_user_agent?: string | null;
  yt_proxy?: string | null;
  manual_speakers?: boolean;
}
