import { useEffect, useState } from 'react'

import { api, ApiError, type Job, type JobLog } from './api'

export interface StageProgress {
  stage: string
  stageProgress: number
  overall: number
  message: string
}

function mergeLogs(current: JobLog[], incoming: JobLog[]) {
  const entries = new Map(current.map((entry) => [entry.id, entry]))
  incoming.forEach((entry) => entries.set(entry.id, entry))
  return [...entries.values()]
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    .slice(-1000)
}

export function useJobStream(jobId: string | undefined) {
  const [job, setJob] = useState<Job | null>(null)
  const [progress, setProgress] = useState<StageProgress | null>(null)
  const [connected, setConnected] = useState(false)
  const [logs, setLogs] = useState<JobLog[]>([])
  const [logError, setLogError] = useState<string | null>(null)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    let finished = false
    setJob(null)
    setProgress(null)
    setLogs([])
    setError(null)
    setLogError(null)
    setConnected(false)

    const source = new EventSource(`/api/jobs/${jobId}/events`)
    const close = () => {
      source.close()
      if (!cancelled) setConnected(false)
    }
    const updateJob = (next: Job) => {
      if (cancelled) return
      setJob((current) => ({ ...next, source: next.source ?? current?.source ?? null }))
      finished = ['done', 'failed', 'cancelled'].includes(next.status)
      if (finished) close()
    }
    const refreshLogs = async () => {
      try {
        const entries = await api.getJobLogs(jobId)
        if (!cancelled) {
          setLogs((current) => mergeLogs(current, entries))
          setLogError(null)
        }
      } catch (reason) {
        if (!cancelled) setLogError(reason instanceof ApiError && reason.status === 404
          ? 'O endpoint de logs não está disponível neste servidor. Encerre o AutoClip com Ctrl+C e inicie-o novamente para carregar a atualização.'
          : 'Não foi possível carregar o histórico de logs. Verifique a conexão com o AutoClip e tente novamente.')
      }
    }
    const refresh = async () => {
      try {
        const next = await api.getJob(jobId)
        updateJob(next)
        if (!cancelled) setError(null)
      } catch (reason) {
        if (!cancelled) setError(reason as Error)
      }
      await refreshLogs()
    }

    void refresh()
    // Reconcile dropped SSE messages and workers running in another process.
    const timer = window.setInterval(() => {
      if (!finished) void refresh()
    }, 5000)
    source.onopen = () => {
      if (!cancelled) setConnected(true)
      void refreshLogs()
    }
    source.addEventListener('snapshot', (event) => {
      updateJob(JSON.parse((event as MessageEvent).data) as Job)
      void refreshLogs()
    })
    source.addEventListener('log', (event) => {
      const { entry } = JSON.parse((event as MessageEvent).data) as { entry: JobLog }
      if (!cancelled) setLogs((current) => mergeLogs(current, [entry]))
    })
    source.addEventListener('progress', (event) => {
      if (cancelled) return
      const data = JSON.parse((event as MessageEvent).data)
      setProgress({
        stage: data.stage,
        stageProgress: data.stage_progress,
        overall: data.overall,
        message: data.message,
      })
      setJob((current) => current
        ? { ...current, status: 'running', current_stage: data.stage, progress: data.overall }
        : current)
    })
    const terminal = (status: Job['status']) => (event: Event) => {
      if (cancelled) return
      const data = JSON.parse((event as MessageEvent).data ?? '{}')
      setJob((current) => current
        ? { ...current, status, error: data.error ?? null, progress: status === 'done' ? 1 : current.progress }
        : current)
      finished = true
      close()
      void refresh()
    }
    source.addEventListener('done', terminal('done'))
    source.addEventListener('failed', terminal('failed'))
    source.addEventListener('cancelled', terminal('cancelled'))
    source.onerror = () => { if (!cancelled) setConnected(false) }

    return () => {
      cancelled = true
      source.close()
      window.clearInterval(timer)
    }
  }, [jobId])

  return { job, progress, connected, logs, logError, error, setJob }
}
