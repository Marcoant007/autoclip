import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api, formatDuration } from '../api'
import { ErrorNote } from '../components/ErrorNote'
import { JobLogs } from '../components/JobLogs'
import { useJobStream } from '../useJobStream'

/** Stage order and labels, mirroring autoclip.pipeline.Stage. */
const STAGES = [
  { key: 'prepare', label: 'Prepare', note: 'Extracting audio and thumbnails' },
  { key: 'transcribe', label: 'Transcribe', note: 'Word-level timing' },
  { key: 'highlights', label: 'Highlights', note: 'Choosing the moments worth cutting' },
  { key: 'reframe', label: 'Reframe', note: 'Tracking the speaker into vertical' },
  { key: 'captions', label: 'Captions', note: 'Building subtitle timing' },
  { key: 'export', label: 'Export', note: 'Rendering clips' },
] as const

export function JobProgress() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const { job, progress, connected, logs, logError, error } = useJobStream(jobId)
  const [cancelling, setCancelling] = useState(false)
  const [actionError, setActionError] = useState<Error | null>(null)

  if (!job) {
    return error ? <div className="pt-14"><ErrorNote error={error} /></div>
      : <p className="pt-24 text-sm text-ink-500">Loading…</p>
  }

  const activeIndex = STAGES.findIndex((s) => s.key === job.current_stage)
  const percent = Math.round(job.progress * 100)

  const cancel = async () => {
    setCancelling(true)
    setActionError(null)
    try {
      await api.cancelJob(job.id)
    } catch (err) {
      setActionError(err as Error)
    } finally {
      setCancelling(false)
    }
  }

  const retry = async () => {
    setActionError(null)
    try {
      await api.retryJob(job.id)
      window.location.reload()
    } catch (err) {
      setActionError(err as Error)
    }
  }

  return (
    <div className="pt-14">
      <div className="rise flex flex-wrap items-baseline justify-between gap-6 border-b border-ink-800 pb-6">
        <div className="min-w-0">
          <p className="eyebrow">{job.status}</p>
          <h1 className="mt-2 max-w-3xl truncate font-display text-[clamp(1.75rem,4vw,3rem)] leading-tight text-ink-100">
            {job.source?.title || 'Untitled'}
          </h1>
          {job.source && (
            <p className="numeric mt-2 text-xs text-ink-500">
              {formatDuration(job.source.duration_s)}
              {job.source.width ? ` · ${job.source.width}×${job.source.height}` : ''} ·{' '}
              {job.provider}
            </p>
          )}
        </div>

        <div className="flex items-baseline gap-8">
          <span className="numeric font-display text-[clamp(2.5rem,6vw,4rem)] leading-none text-accent-500">
            {percent}
            <span className="text-2xl text-ink-600">%</span>
          </span>
          {(job.status === 'running' || job.status === 'queued') && (
            <button onClick={cancel} disabled={cancelling} className="btn btn-ghost">
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          )}
          {(job.status === 'failed' || job.status === 'cancelled') && (
            <button onClick={retry} className="btn btn-primary">
              Retry
            </button>
          )}
          {job.status === 'done' && (
            <button onClick={() => navigate(`/jobs/${job.id}/clips`)} className="btn btn-primary">
              Review clips
            </button>
          )}
        </div>
      </div>

      {job.error && (
        <div className="mt-8 max-w-3xl">
          <ErrorNote error={new Error(job.error)} />
          <p className="mt-3 text-xs text-ink-500">
            Retrying resumes from the stage that failed — finished stages are not redone.
          </p>
        </div>
      )}

      {actionError && (
        <div className="mt-8 max-w-3xl">
          <ErrorNote error={actionError} onDismiss={() => setActionError(null)} />
        </div>
      )}

      <div className="mt-10 grid items-start gap-8 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
      <section className="min-w-0 rounded-xl border border-ink-800 bg-ink-850/30 px-5 pb-2">
      <div className="flex items-center justify-between border-b border-ink-800 py-5">
        <h2 className="text-sm font-semibold text-ink-100">Etapas do processamento</h2>
        <span className="numeric text-xs text-accent-400">{STAGES.filter((_, index) => job.status === 'done' || index < activeIndex).length} / {STAGES.length}</span>
      </div>
      <ol>
        {STAGES.map((stage, index) => {
          // A failed job stopped *at* current_stage, so that stage must read as
          // failed rather than as still running — otherwise the checklist claims
          // work is in progress while the banner says it died.
          const failedHere =
            (job.status === 'failed' || job.status === 'cancelled') && index === activeIndex

          const state =
            job.status === 'done' || (activeIndex >= 0 && index < activeIndex)
              ? 'done'
              : failedHere
                ? 'stopped'
                : index === activeIndex && job.status === 'running'
                  ? 'active'
                  : 'pending'

          const fraction =
            state === 'done' ? 1 : state === 'active' && progress?.stage === stage.key ? progress.stageProgress : 0

          return (
            <li
              key={stage.key}
              className="rise grid grid-cols-[2.5rem_1fr] items-start gap-x-5 border-b border-ink-850 py-5"
              style={{ animationDelay: `${index * 55}ms` }}
            >
              <span
                className={[
                  'numeric pt-0.5 text-xs',
                  state === 'done'
                    ? 'text-signal-good'
                    : state === 'stopped'
                      ? 'text-signal-bad'
                      : state === 'active'
                        ? 'text-accent-500'
                        : 'text-ink-600',
                ].join(' ')}
              >
                {state === 'done' ? '✓' : state === 'stopped' ? '✕' : String(index + 1).padStart(2, '0')}
              </span>

              <div>
                <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                  <span
                    className={[
                      'text-[0.9375rem]',
                      state === 'pending' ? 'text-ink-600' : 'text-ink-100',
                    ].join(' ')}
                  >
                    {stage.label}
                  </span>
                  <span
                    className={`text-xs ${state === 'stopped' ? 'text-signal-bad' : 'text-ink-500'}`}
                  >
                    {state === 'stopped'
                      ? job.status === 'cancelled'
                        ? 'cancelled here'
                        : 'failed here'
                      : state === 'active'
                        ? (progress?.message ?? stage.note)
                        : stage.note}
                  </span>
                </div>

                {/* A hairline that fills. No track chrome — the rule below the
                    row already provides the container. */}
                <div className="mt-3 h-px w-full bg-ink-800">
                  <div
                    className="h-px origin-left bg-accent-500 transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]"
                    style={{ transform: `scaleX(${fraction})` }}
                  />
                </div>
              </div>
            </li>
          )
        })}
      </ol>
      </section>
      <JobLogs entries={logs} connected={connected}
        active={job.status === 'running' || job.status === 'queued'} error={logError} />
      </div>
    </div>
  )
}
