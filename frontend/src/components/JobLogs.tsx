import { useEffect, useMemo, useRef, useState } from 'react'

import type { JobLog } from '../api'

interface Props {
  entries: JobLog[]
  connected: boolean
  active: boolean
  error: string | null
}

export function JobLogs({ entries, connected, active, error }: Props) {
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [follow, setFollow] = useState(true)
  const [notice, setNotice] = useState('')
  const viewport = useRef<HTMLDivElement>(null)
  const filtered = useMemo(() => entries.filter((entry) => {
    const levelMatches = filter === 'all' || (filter === 'warning'
      ? entry.level === 'WARNING'
      : ['ERROR', 'CRITICAL'].includes(entry.level))
    const matchesSearch = `${entry.message} ${entry.logger}`.toLowerCase().includes(search.toLowerCase())
    return levelMatches && matchesSearch
  }), [entries, filter, search])
  const text = filtered.map((entry) =>
    `${entry.timestamp} [${entry.level}] ${entry.logger}: ${entry.message}`).join('\n')

  useEffect(() => {
    if (follow && viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight
  }, [filtered, follow])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2500)
    return () => window.clearTimeout(timer)
  }, [notice])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setNotice('Logs copiados.')
    } catch {
      setNotice('Não foi possível copiar. Use a opção Baixar.')
    }
  }

  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'autoclip-logs.txt'
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <section aria-labelledby="job-logs-title" className="min-w-0 overflow-hidden rounded-2xl border border-ink-800 bg-ink-850/70">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-800 px-5 py-4">
        <div className="flex items-center gap-3">
          <span aria-hidden="true" className="font-mono text-xl text-accent-400">›_</span>
          <h2 id="job-logs-title" className="text-sm font-semibold text-ink-100">Logs do processamento</h2>
        </div>
        <span className="flex items-center gap-2 text-xs text-ink-400">
          <span className={`size-1.5 rounded-full ${active && connected ? 'bg-accent-400 motion-safe:animate-pulse' : 'bg-ink-600'}`} />
          {active ? connected ? 'Ao vivo' : 'Reconectando' : 'Histórico'}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-b border-ink-800 px-5 py-3">
        <label className="sr-only" htmlFor="log-search">Buscar nos logs</label>
        <input id="log-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar nos logs…" className="input min-w-32 flex-1 !py-2 !text-xs" />
        <label className="sr-only" htmlFor="log-level">Filtrar por nível</label>
        <select id="log-level" value={filter} onChange={(event) => setFilter(event.target.value)}
          className="input !w-auto !py-2 !text-xs">
          <option value="all">Todos os níveis</option>
          <option value="warning">Avisos</option>
          <option value="error">Erros</option>
        </select>
      </div>

      {error && <p role="alert" className="border-b border-ink-800 px-5 py-3 text-xs text-signal-bad">{error}</p>}
      <div ref={viewport} tabIndex={0} aria-label="Histórico de logs"
        className="h-[420px] overflow-auto bg-ink-900/80 px-5 py-4 font-mono text-[11px] leading-6 sm:text-xs">
        {filtered.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center font-sans">
            <span aria-hidden="true" className="mb-2 font-mono text-3xl text-ink-600">›_</span>
            <p className="text-sm text-ink-300">{error ? 'Histórico indisponível' : entries.length ? 'Nenhum log corresponde ao filtro.' : 'Nenhum log registrado ainda.'}</p>
            <p className="max-w-xs text-xs leading-relaxed text-ink-500">
              {error ? 'Depois de resolver a conexão ou reiniciar o servidor, recarregue esta página. O processamento não será refeito.' : entries.length ? 'Tente outro nível ou termo de busca.' : active
                ? 'As mensagens aparecerão aqui assim que o processamento começar.'
                : 'Jobs anteriores à atualização não possuem histórico de logs.'}
            </p>
            {error && <button className="btn btn-ghost mt-3" onClick={() => window.location.reload()}>Recarregar histórico</button>}
          </div>
        ) : filtered.map((entry) => (
          <div key={entry.id} className="grid grid-cols-[auto_1fr] items-start gap-x-3 border-b border-ink-850 py-2 sm:grid-cols-[auto_auto_1fr] sm:py-1.5">
            <time dateTime={entry.timestamp} title={entry.timestamp} className="numeric text-ink-500">
              {new Date(entry.timestamp).toLocaleTimeString('pt-BR', { hour12: false })}
            </time>
            <span className={`w-[4.5rem] text-[10px] font-semibold ${['ERROR', 'CRITICAL'].includes(entry.level)
              ? 'text-signal-bad' : entry.level === 'WARNING' ? 'text-yellow-300' : 'text-accent-400'}`}>
              {entry.level}
            </span>
            <div className="col-span-2 min-w-0 sm:col-span-1">
              <span className="mb-0.5 block text-[10px] leading-4 text-ink-600">{entry.logger.replace(/^autoclip\./, '')}</span>
              <p className="whitespace-pre-wrap break-words text-ink-200 [overflow-wrap:anywhere]">{entry.message}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-800 px-5 py-3">
        <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-400">
          <input type="checkbox" checked={follow} onChange={(event) => setFollow(event.target.checked)} className="accent-accent-500" />
          Acompanhar
        </label>
        <span className="numeric text-[11px] text-ink-500">{filtered.length} / {entries.length} registros</span>
        <div className="flex gap-2">
          <button className="btn btn-ghost btn-sm" onClick={copy} disabled={!filtered.length}>Copiar</button>
          <button className="btn btn-ghost btn-sm" onClick={download} disabled={!filtered.length}>Baixar</button>
        </div>
      </div>
      <p role="status" className={notice ? 'border-t border-ink-800 px-5 py-2 text-xs text-accent-400' : 'sr-only'}>
        {notice || `${entries.length} registros no histórico.`}
      </p>
    </section>
  )
}
