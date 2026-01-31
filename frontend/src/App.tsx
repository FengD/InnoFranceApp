import { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteJob,
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
  const [showHistory, setShowHistory] = useState(true);

  const refreshJobs = useCallback(async () => {
    try {
      const data = await listJobs(false);
      const ordered = data.jobs
        .slice()
        .sort((a, b) => b.created_at.localeCompare(a.created_at));
      setJobs(ordered);
      const active = ordered.filter(
        (job) => job.status === "queued" || job.status === "running"
      );
      if (active.length > 0) {
        const fresh = await Promise.all(active.map((job) => getJob(job.job_id)));
        setJobs((prev) =>
          prev.map((job) => fresh.find((f) => f.job_id === job.job_id) ?? job)
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
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

  useEffect(() => {
    if (jobs.every((job) => job.status === "completed" || job.status === "failed")) {
      return;
    }
    const timer = window.setInterval(() => {
      refreshJobs();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [jobs, refreshJobs]);

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
                      steps: upsertStep(j.steps, {
                        step: step.step ?? "",
                        status: step.status ?? "",
                        message: step.message ?? "",
                        detail: step.detail ?? null,
                        timestamp: step.timestamp ?? new Date().toISOString(),
                      }),
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

  const handleDeleteJob = useCallback(async (jobId: string) => {
    const confirmed = window.confirm("Delete this history record?");
    if (!confirmed) return;
    try {
      await deleteJob(jobId);
      setJobs((prev) => prev.filter((job) => job.job_id !== jobId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete job");
    }
  }, []);

  const activeJobs = useMemo(
    () => jobs.filter((job) => job.status === "queued" || job.status === "running"),
    [jobs]
  );
  const historyJobs = useMemo(
    () => jobs.filter((job) => job.status === "completed" || job.status === "failed"),
    [jobs]
  );

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
          <h2>Current pipelines</h2>
          <p className="muted">
            Up to {settings?.max_queued ?? 3} pipelines (queued + running).
            {settings?.parallel_enabled
              ? ` Up to ${settings?.max_concurrent} run in parallel.`
              : " One runs at a time."}
          </p>
          <div className="job-list">
            {activeJobs.length === 0 ? (
              <p className="muted">No pipelines yet. Start one above.</p>
            ) : (
              activeJobs.map((job) => (
                <JobCard
                  key={job.job_id}
                  job={job}
                  onRefresh={() => handleRefreshJob(job.job_id)}
                />
              ))
            )}
          </div>
        </section>
        <section className="section">
          <div className="section-header">
            <h2>History</h2>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setShowHistory((v) => !v)}
              aria-expanded={showHistory}
            >
              {showHistory ? "Hide" : "Show"}
            </button>
          </div>
          {showHistory && (
            <div className="job-list">
              {historyJobs.length === 0 ? (
                <p className="muted">No completed pipelines yet.</p>
              ) : (
                historyJobs.map((job) => (
                  <JobCard
                    key={job.job_id}
                    job={job}
                    onRefresh={() => handleRefreshJob(job.job_id)}
                    onDelete={() => handleDeleteJob(job.job_id)}
                  />
                ))
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;

function upsertStep(steps: PipelineJob["steps"], nextStep: PipelineJob["steps"][number]) {
  const index = steps.findIndex((s) => s.step === nextStep.step);
  if (index === -1) {
    return [...steps, nextStep];
  }
  return steps.map((s, i) => (i === index ? { ...s, ...nextStep } : s));
}
