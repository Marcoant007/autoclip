import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, formatDuration } from '../api'
import { ErrorNote } from '../components/ErrorNote'
import { Icon, Spinner, type IconName } from '../components/Icon'
import { JobLogs } from '../components/JobLogs'
import { Callout, Loading, PageHeader, ProgressBar, StatusBadge } from '../components/ui'
import { useJobStream } from '../useJobStream'

/** Stage order and labels, mirroring autoclip.pipeline.Stage. */
const STAGES: { key: string; label: string; note: string; icon: IconName }[] = [
  { key: 'prepare', label: 'Preparar', note: 'Extraindo áudio e miniaturas', icon: 'film' },
  { key: 'transcribe', label: 'Transcrever', note: 'Transcrição palavra por palavra', icon: 'captions' },
  { key: 'highlights', label: 'Encontrar destaques', note: 'A IA escolhe os melhores momentos', icon: 'wand' },
  { key: 'reframe', label: 'Enquadrar', note: 'Seguindo quem fala no formato vertical', icon: 'ratio' },
  { key: 'captions', label: 'Legendas', note: 'Sincronizando o texto com a fala', icon: 'type' },
  { key: 'export', label: 'Exportar', note: 'Renderizando os cortes', icon: 'download' },
]

export function JobProgress() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const { job, progress, connected, logs, logError, error } = useJobStream(jobId)
  const [cancelling, setCancelling] = useState(false)
  const [actionError, setActionError] = useState<Error | null>(null)
  const [showLogs, setShowLogs] = useState(false)

  if (!job) {
    return error ? (
      <div className="max-w-3xl">
        <ErrorNote error={error} />
      </div>
    ) : (
      <Loading label="Carregando processamento…" />
    )
  }

  const activeIndex = STAGES.findIndex((s) => s.key === job.current_stage)
  const percent = Math.round(job.progress * 100)
  const running = job.status === 'running' || job.status === 'queued'
  const stopped = job.status === 'failed' || job.status === 'cancelled'
  const logsVisible = showLogs || stopped

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

  const currentStage = STAGES[activeIndex]

  return (
    <div>
      <PageHeader
        back={{ to: '/clips', label: 'Cortar vídeo' }}
        eyebrow={<StatusBadge status={job.status} />}
        title={<span className="line-clamp-2">{job.source?.title || 'Sem título'}</span>}
        description={
          job.source && (
            <span className="numeric flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              <span className="flex items-center gap-1.5"><Icon name="clock" size={14} />{formatDuration(job.source.duration_s)}</span>
              {job.source.width && <span>{job.source.width}×{job.source.height}</span>}
              <span className="flex items-center gap-1.5"><Icon name="wand" size={14} />{job.provider}</span>
            </span>
          )
        }
      />

      {/* Overall status */}
      <section
        className={[
          'rise mt-8 overflow-hidden rounded-2xl border p-5 sm:p-7',
          job.status === 'done'
            ? 'border-signal-good/30 bg-gradient-to-br from-accent-900/60 to-ink-850'
            : stopped
              ? 'border-signal-bad/30 bg-ink-850'
              : 'border-ink-800 bg-ink-850',
        ].join(' ')}
        style={{ animationDelay: '60ms' }}
      >
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div className="flex min-w-0 items-center gap-5">
            <span
              className={[
                'grid size-14 shrink-0 place-items-center rounded-2xl',
                job.status === 'done'
                  ? 'bg-signal-good text-ink-950'
                  : stopped
                    ? 'bg-signal-bad/15 text-signal-bad'
                    : 'bg-accent-500/15 text-accent-400',
              ].join(' ')}
            >
              {job.status === 'done' ? (
                <Icon name="check" size={26} strokeWidth={2.6} />
              ) : stopped ? (
                <Icon name="alert" size={24} />
              ) : (
                <Spinner size={24} />
              )}
            </span>
            <div className="min-w-0">
              <p className="text-lg font-semibold text-ink-100">
                {job.status === 'done'
                  ? 'Seus cortes estão prontos!'
                  : job.status === 'failed'
                    ? 'O processamento parou'
                    : job.status === 'cancelled'
                      ? 'Processamento cancelado'
                      : job.status === 'queued'
                        ? 'Na fila, começando em instantes…'
                        : currentStage
                          ? `${currentStage.label}…`
                          : 'Processando…'}
              </p>
              <p className="mt-0.5 text-sm text-ink-400">
                {job.status === 'done'
                  ? 'Revise, ajuste e exporte os que você gostar.'
                  : stopped
                    ? 'Tentar de novo retoma da etapa que falhou — o que já terminou não é refeito.'
                    : (progress?.message ?? currentStage?.note ?? 'Você pode sair desta página; o processamento continua.')}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-5">
            <span className="numeric font-display text-5xl leading-none text-ink-100">
              {percent}
              <span className="text-2xl text-ink-500">%</span>
            </span>
            {running && (
              <button onClick={cancel} disabled={cancelling} className="btn btn-ghost">
                <Icon name="x" size={15} />
                {cancelling ? 'Cancelando…' : 'Cancelar'}
              </button>
            )}
            {stopped && (
              <button onClick={retry} className="btn btn-primary">
                <Icon name="refresh" size={15} />
                Tentar de novo
              </button>
            )}
            {job.status === 'done' && (
              <button onClick={() => navigate(`/jobs/${job.id}/clips`)} className="btn btn-primary btn-lg">
                Revisar cortes
                <Icon name="arrowRight" size={16} />
              </button>
            )}
          </div>
        </div>
        <ProgressBar
          value={job.progress}
          tone={job.status === 'done' ? 'good' : stopped ? 'bad' : 'accent'}
          animated={job.status === 'running'}
          className="mt-6 !h-2"
        />
      </section>

      {job.error && (
        <div className="mt-6 max-w-4xl">
          <ErrorNote error={new Error(job.error)} />
        </div>
      )}

      {actionError && (
        <div className="mt-6 max-w-4xl">
          <ErrorNote error={actionError} onDismiss={() => setActionError(null)} />
        </div>
      )}

      {/* Stages */}
      <section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {STAGES.map((stage, index) => {
          // A failed job stopped *at* current_stage, so that stage must read as
          // failed rather than as still running.
          const failedHere = stopped && index === activeIndex
          const state =
            job.status === 'done' || (activeIndex >= 0 && index < activeIndex)
              ? 'done'
              : failedHere
                ? 'stopped'
                : index === activeIndex && job.status === 'running'
                  ? 'active'
                  : 'pending'

          const fraction =
            state === 'done'
              ? 1
              : state === 'active' && progress?.stage === stage.key
                ? progress.stageProgress
                : 0

          return (
            <div
              key={stage.key}
              className={[
                'rise rounded-xl border p-4 transition-colors',
                state === 'active'
                  ? 'border-accent-600/60 bg-accent-500/[0.05]'
                  : state === 'stopped'
                    ? 'border-signal-bad/40 bg-signal-bad/[0.04]'
                    : 'border-ink-800 bg-ink-850/60',
              ].join(' ')}
              style={{ animationDelay: `${100 + index * 45}ms` }}
            >
              <div className="flex items-center gap-3">
                <span
                  className={[
                    'grid size-9 shrink-0 place-items-center rounded-lg',
                    state === 'done'
                      ? 'bg-signal-good/15 text-signal-good'
                      : state === 'stopped'
                        ? 'bg-signal-bad/15 text-signal-bad'
                        : state === 'active'
                          ? 'bg-accent-500 text-ink-950'
                          : 'bg-ink-800 text-ink-500',
                  ].join(' ')}
                >
                  {state === 'done' ? (
                    <Icon name="check" size={17} strokeWidth={2.6} />
                  ) : state === 'stopped' ? (
                    <Icon name="x" size={17} strokeWidth={2.6} />
                  ) : state === 'active' ? (
                    <Spinner size={17} />
                  ) : (
                    <Icon name={stage.icon} size={17} />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <p className={`text-sm font-semibold ${state === 'pending' ? 'text-ink-500' : 'text-ink-100'}`}>
                    <span className="numeric mr-1.5 text-ink-600">{index + 1}.</span>
                    {stage.label}
                  </p>
                  <p
                    className={`truncate text-xs ${state === 'stopped' ? 'text-signal-bad' : 'text-ink-500'}`}
                  >
                    {state === 'stopped'
                      ? job.status === 'cancelled'
                        ? 'Cancelado nesta etapa'
                        : 'Falhou nesta etapa'
                      : state === 'active'
                        ? (progress?.message ?? stage.note)
                        : stage.note}
                  </p>
                </div>
              </div>
              {state === 'active' && <ProgressBar value={fraction} className="mt-3 !h-1" />}
            </div>
          )
        })}
      </section>

      {/* Logs */}
      <section className="mt-8">
        {!stopped && (
          <button
            type="button"
            onClick={() => setShowLogs((v) => !v)}
            aria-expanded={logsVisible}
            className="btn btn-quiet -ml-2"
          >
            <Icon name="terminal" size={15} />
            {logsVisible ? 'Ocultar detalhes técnicos' : 'Ver detalhes técnicos (logs)'}
            <Icon name="chevronDown" size={15} className={logsVisible ? 'rotate-180' : ''} />
          </button>
        )}
        {logsVisible && (
          <div className="fade-in mt-3">
            {stopped && (
              <div className="mb-4">
                <Callout tone="info">
                  Os logs abaixo ajudam a entender o que aconteceu. Use <strong>Copiar</strong> para
                  compartilhar ao pedir ajuda.
                </Callout>
              </div>
            )}
            <JobLogs entries={logs} connected={connected} active={running} error={logError} />
          </div>
        )}
      </section>

      {job.status === 'done' && (
        <p className="mt-8 text-sm text-ink-500">
          Quer cortar outro vídeo?{' '}
          <Link to="/clips" className="link">Enviar novo vídeo</Link>
        </p>
      )}
    </div>
  )
}
