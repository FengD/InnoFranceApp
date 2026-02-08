import { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteJob,
  getJob,
  getMe,
  getSettings,
  listJobs,
  login,
  logout,
  reorderQueue,
  startPipeline,
  startWeChatLogin,
  streamJobEvents,
  updateJobMetadata,
  updateSettings,
} from "./api";
import type { PipelineJob, SettingsResponse, User } from "./types";
import { JobCard } from "./components/JobCard";
import { LoginPanel } from "./components/LoginPanel";
import { PipelineForm } from "./components/PipelineForm";
import { SettingsPanel } from "./components/SettingsPanel";

function App() {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<PipelineJob[]>([]);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(true);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  const [filterTags, setFilterTags] = useState<string[]>([]);
  const [filterPublished, setFilterPublished] = useState<boolean | null>(null);

  const refreshJobs = useCallback(async () => {
    const active = jobs.filter(
      (job) => job.status === "queued" || job.status === "running"
    );
    if (active.length === 0) return;
    try {
      const fresh = await Promise.all(active.map((job) => getJob(job.job_id)));
      setJobs((prev) =>
        prev.map((job) => fresh.find((f) => f.job_id === job.job_id) ?? job)
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to refresh jobs");
    }
  }, [jobs]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setAuthLoading(true);
      setAuthError(null);
      try {
        const me = await getMe();
        if (!cancelled) setCurrentUser(me);
      } catch {
        if (!cancelled) setCurrentUser(null);
      } finally {
        if (!cancelled) setAuthLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!currentUser) {
      setJobs([]);
      setSettings(null);
      setLoading(false);
      return;
    }
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
          if (e instanceof Error && e.message.toLowerCase().includes("unauthorized")) {
            setCurrentUser(null);
            setAuthError("Please sign in to continue.");
          } else {
            setError(e instanceof Error ? e.message : "Failed to load");
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentUser]);

  useEffect(() => {
    const stored = window.localStorage.getItem("innofrance-theme");
    if (stored === "light" || stored === "dark") {
      setTheme(stored);
    }
  }, []);

  useEffect(() => {
    document.body.classList.toggle("theme-light", theme === "light");
    window.localStorage.setItem("innofrance-theme", theme);
  }, [theme]);

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
    async (patch: {
      parallel_enabled?: boolean;
      max_concurrent?: number;
      tags?: string[];
    }) => {
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
    const confirmed = window.confirm("Delete this pipeline?");
    if (!confirmed) return;
    try {
      await deleteJob(jobId);
      setJobs((prev) => prev.filter((job) => job.job_id !== jobId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete job");
    }
  }, []);

  const handleUpdateJobMeta = useCallback(
    async (
      jobId: string,
      patch: {
        note?: string | null;
        custom_name?: string | null;
        tags?: string[];
        published?: boolean;
      }
    ) => {
      try {
        const updated = await updateJobMetadata(jobId, patch);
        setJobs((prev) => prev.map((job) => (job.job_id === jobId ? updated : job)));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to update pipeline");
        throw e;
      }
    },
    []
  );

  const activeJobs = useMemo(
    () => jobs.filter((job) => job.status === "queued" || job.status === "running"),
    [jobs]
  );
  const queuedJobs = useMemo(
    () =>
      jobs
        .filter((job) => job.status === "queued")
        .slice()
        .sort((a, b) => {
          const posA = a.queue_position ?? Number.MAX_SAFE_INTEGER;
          const posB = b.queue_position ?? Number.MAX_SAFE_INTEGER;
          if (posA !== posB) return posA - posB;
          return a.created_at.localeCompare(b.created_at);
        }),
    [jobs]
  );
  const runningJobs = useMemo(
    () =>
      jobs
        .filter((job) => job.status === "running")
        .slice()
        .sort((a, b) => {
          const aTime = a.started_at ?? a.created_at;
          const bTime = b.started_at ?? b.created_at;
          return bTime.localeCompare(aTime);
        }),
    [jobs]
  );
  const historyJobs = useMemo(
    () =>
      jobs
        .filter((job) => job.status === "completed" || job.status === "failed")
        .filter((job) => {
          if (filterPublished === null) return true;
          return Boolean(job.published) === filterPublished;
        })
        .filter((job) => {
          if (filterTags.length === 0) return true;
          const jobTags = job.tags ?? [];
          return filterTags.every((tag) => jobTags.includes(tag));
        })
        .slice()
        .sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [filterPublished, filterTags, jobs]
  );

  const handleReorderQueue = useCallback(
    async (nextOrder: string[]) => {
      setJobs((prev) =>
        prev.map((job) =>
          job.status === "queued"
            ? {
                ...job,
                queue_position: nextOrder.indexOf(job.job_id),
              }
            : job
        )
      );
      try {
        const res = await reorderQueue(nextOrder);
        setJobs(res.jobs);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to reorder queue");
        try {
          const res = await listJobs();
          setJobs(res.jobs);
        } catch {
          // ignore
        }
      }
    },
    []
  );

  const handleQueueDrop = useCallback(
    async (targetId: string | null) => {
      if (!draggingId) return;
      const currentOrder = queuedJobs.map((job) => job.job_id);
      const fromIndex = currentOrder.indexOf(draggingId);
      if (fromIndex === -1) return;
      const toIndex =
        targetId === null ? currentOrder.length - 1 : currentOrder.indexOf(targetId);
      if (toIndex === -1 || fromIndex === toIndex) {
        setDraggingId(null);
        setDragOverId(null);
        return;
      }
      const nextOrder = moveItem(currentOrder, fromIndex, toIndex);
      setDraggingId(null);
      setDragOverId(null);
      await handleReorderQueue(nextOrder);
    },
    [draggingId, handleReorderQueue, queuedJobs]
  );

  if (authLoading) {
    return (
      <div style={{ padding: "2rem", textAlign: "center" }}>
        Checking session…
      </div>
    );
  }

  if (!currentUser) {
    return (
      <LoginPanel
        error={authError}
        onLogin={async (username, password) => {
          setAuthError(null);
          try {
            const user = await login(username, password);
            setCurrentUser(user);
          } catch (e) {
            setAuthError(e instanceof Error ? e.message : "Failed to sign in");
          }
        }}
        onWeChatLogin={async () => {
          setAuthError(null);
          try {
            const res = await startWeChatLogin(window.location.origin);
            window.location.assign(res.url);
          } catch (e) {
            setAuthError(e instanceof Error ? e.message : "WeChat login failed");
          }
        }}
      />
    );
  }

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
        <div className="header-actions">
          <span className="muted">Signed in as {currentUser.username}</span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={async () => {
              await logout();
              setCurrentUser(null);
            }}
          >
            Sign out
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() =>
              setTheme((prev) => (prev === "dark" ? "light" : "dark"))
            }
          >
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setSettingsOpen((o) => !o)}
            aria-expanded={settingsOpen}
          >
            Settings
          </button>
        </div>
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
            providerAvailability={settings?.provider_availability ?? {}}
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
              <>
                {runningJobs.map((job) => (
                  <JobCard
                    key={job.job_id}
                    job={job}
                    onRefresh={() => handleRefreshJob(job.job_id)}
                  />
                ))}
                {queuedJobs.length > 0 && (
                  <div
                    className="job-queue"
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      handleQueueDrop(null);
                    }}
                  >
                    <div className="job-queue-header">
                      <h3>Waiting queue</h3>
                      <span className="muted">Drag to reorder</span>
                    </div>
                    {queuedJobs.map((job) => (
                      <div
                        key={job.job_id}
                        className={`job-card-draggable${
                          draggingId === job.job_id ? " is-dragging" : ""
                        }${dragOverId === job.job_id ? " is-dragover" : ""}`}
                        draggable
                        onDragStart={(e) => {
                          const target = e.target as HTMLElement | null;
                          if (target && target.closest("button, a, input, textarea, select")) {
                            e.preventDefault();
                            return;
                          }
                          e.dataTransfer.setData("text/plain", job.job_id);
                          e.dataTransfer.effectAllowed = "move";
                          setDraggingId(job.job_id);
                        }}
                        onDragOver={(e) => {
                          e.preventDefault();
                          setDragOverId(job.job_id);
                        }}
                        onDragLeave={() => setDragOverId(null)}
                        onDrop={(e) => {
                          e.preventDefault();
                          handleQueueDrop(job.job_id);
                        }}
                      >
                        <JobCard
                          job={job}
                          onRefresh={() => handleRefreshJob(job.job_id)}
                          onDelete={() => handleDeleteJob(job.job_id)}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </section>
        <section className="section">
          <div className="section-header">
            <h2>History</h2>
            {settings?.tags?.length ? (
              <div className="history-filters">
                <span className="muted">Filter:</span>
                {settings.tags.map((tag) => {
                  const active = filterTags.includes(tag);
                  return (
                    <button
                      key={tag}
                      type="button"
                      className={`tag-chip${active ? " is-active" : ""}`}
                      onClick={() =>
                        setFilterTags((prev) =>
                          prev.includes(tag)
                            ? prev.filter((item) => item !== tag)
                            : [...prev, tag]
                        )
                      }
                    >
                      {tag}
                    </button>
                  );
                })}
                <button
                  type="button"
                  className={`tag-chip${filterPublished === true ? " is-active" : ""}`}
                  onClick={() =>
                    setFilterPublished((prev) => (prev === true ? null : true))
                  }
                >
                  Published
                </button>
                <button
                  type="button"
                  className={`tag-chip${filterPublished === false ? " is-active" : ""}`}
                  onClick={() =>
                    setFilterPublished((prev) => (prev === false ? null : false))
                  }
                >
                  Unpublished
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setFilterTags([]);
                    setFilterPublished(null);
                  }}
                >
                  Clear
                </button>
              </div>
            ) : null}
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
                    availableTags={settings?.tags ?? []}
                    onUpdateMeta={(patch) => handleUpdateJobMeta(job.job_id, patch)}
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

function moveItem(items: string[], fromIndex: number, toIndex: number): string[] {
  const next = items.slice();
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}
