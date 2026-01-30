import { useCallback, useEffect, useState } from "react";
import {
  getJob,
  getSettings,
  listJobs,
  startPipeline,
  streamJobEvents,
  updateSettings,
} from "./api";
import type { PipelineJob, SettingsResponse } from "./types";
import { JobCard } from "./components/JobCard";
import { PipelineForm } from "./components/PipelineForm";
import { SettingsPanel } from "./components/SettingsPanel";

function App() {
  const [jobs, setJobs] = useState<PipelineJob[]>([]);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshJobs = useCallback(async () => {
    try {
      const data = await listJobs();
      setJobs(data.jobs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
    }
  }, []);

  const refreshSettings = useCallback(async () => {
    try {
      const data = await getSettings();
      setSettings(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [jobsRes, settingsRes] = await Promise.all([
          listJobs(),
          getSettings(),
        ]);
        if (!cancelled) {
          setJobs(jobsRes.jobs);
          setSettings(settingsRes);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleStart = useCallback(
    async (body: Parameters<typeof startPipeline>[0]) => {
      setError(null);
      try {
        const job = await startPipeline(body);
        setJobs((prev) => [job, ...prev]);
        const unsub = streamJobEvents(job.job_id, async (event, data) => {
          if (event === "progress" && typeof data === "object" && data !== null) {
            const step = data as {
              step?: string;
              status?: string;
              message?: string;
              detail?: string | null;
              timestamp?: string;
            };
            setJobs((prev) =>
              prev.map((j) =>
                j.job_id === job.job_id
                  ? {
                      ...j,
                      steps: [
                        ...j.steps,
                        {
                          step: step.step ?? "",
                          status: step.status ?? "",
                          message: step.message ?? "",
                          detail: step.detail ?? null,
                          timestamp: step.timestamp ?? new Date().toISOString(),
                        },
                      ],
                    }
                  : j
              )
            );
          }
          if (event === "done") {
            const updated = await getJob(job.job_id);
            setJobs((prev) =>
              prev.map((j) => (j.job_id === job.job_id ? updated : j))
            );
            unsub();
          }
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to start pipeline");
      }
    },
    []
  );

  const handleSettingsChange = useCallback(
    async (patch: { parallel_enabled?: boolean; max_concurrent?: number }) => {
      try {
        const next = await updateSettings(patch);
        setSettings(next);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to update settings");
      }
    },
    []
  );

  const handleRefreshJob = useCallback(async (jobId: string) => {
    try {
      const job = await getJob(jobId);
      setJobs((prev) =>
        prev.map((j) => (j.job_id === jobId ? job : j))
      );
    } catch {
      // ignore
    }
  }, []);

  if (loading) {
    return (
      <div style={{ padding: "2rem", textAlign: "center" }}>
        Loading…
      </div>
    );
  }

  return (
    <div className="app">
      <header className="header">
        <h1>InnoFrance Pipeline</h1>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setSettingsOpen((o) => !o)}
          aria-expanded={settingsOpen}
        >
          Settings
        </button>
      </header>

      {settingsOpen && settings && (
        <SettingsPanel
          settings={settings}
          onUpdate={handleSettingsChange}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {error && (
        <div className="banner banner-error" role="alert">
          {error}
        </div>
      )}

      <main className="main">
        <section className="section">
          <h2>New pipeline</h2>
          <PipelineForm
            onStart={handleStart}
            disabled={
              jobs.filter((j) => j.status === "queued" || j.status === "running")
                .length >= (settings?.max_queued ?? 3)
            }
            maxQueued={settings?.max_queued ?? 3}
          />
        </section>

        <section className="section">
          <h2>Pipelines</h2>
          <p className="muted">
            Up to {settings?.max_queued ?? 3} pipelines (queued + running).
            {settings?.parallel_enabled
              ? ` Up to ${settings?.max_concurrent} run in parallel.`
              : " One runs at a time."}
          </p>
          <div className="job-list">
            {jobs.length === 0 ? (
              <p className="muted">No pipelines yet. Start one above.</p>
            ) : (
              jobs.map((job) => (
                <JobCard
                  key={job.job_id}
                  job={job}
                  onRefresh={() => handleRefreshJob(job.job_id)}
                />
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
