import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  api,
  formatBytes,
  formatDuration,
  type CaptionStyle,
  type Clip,
  type CropPath,
  type Job,
  type Word,
} from '../api'
import { CaptionEditor } from '../components/CaptionEditor'
import { ClipPlayer } from '../components/ClipPlayer'
import { ErrorNote } from '../components/ErrorNote'
import { Icon, Spinner } from '../components/Icon'
import { TrimBar } from '../components/TrimBar'
import { EmptyState, Loading, PageHeader, Segmented } from '../components/ui'

const RATIOS = [
  { value: '9:16', label: '9:16', hint: 'Reels, TikTok, Shorts' },
  { value: '1:1', label: '1:1', hint: 'Feed quadrado' },
  { value: '16:9', label: '16:9', hint: 'YouTube horizontal' },
] as const

type Tab = 'about' | 'text' | 'look'
type Filter = 'all' | 'kept' | 'candidate' | 'discarded'

export function Review() {
  const { jobId } = useParams()
  const [job, setJob] = useState<Job | null>(null)
  const [clips, setClips] = useState<Clip[]>([])
  const [styles, setStyles] = useState<CaptionStyle[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [words, setWords] = useState<Word[]>([])
  const [cropPath, setCropPath] = useState<CropPath | null>(null)
  const [wordsDirty, setWordsDirty] = useState(false)
  const [savingWords, setSavingWords] = useState(false)
  const [exporting, setExporting] = useState<Set<string>>(new Set())
  const [error, setError] = useState<Error | null>(null)
  const [tab, setTab] = useState<Tab>('about')
  const [filter, setFilter] = useState<Filter>('all')

  useEffect(() => {
    if (!jobId) return
    void Promise.all([api.getJob(jobId), api.listClips(jobId), api.captionStyles()])
      .then(([loadedJob, loadedClips, loadedStyles]) => {
        setJob(loadedJob)
        setClips(loadedClips)
        setStyles(loadedStyles)
        setSelectedId((current) => current ?? loadedClips[0]?.id ?? null)
      })
      .catch((err) => setError(err as Error))
  }, [jobId])

  const selected = useMemo(
    () => clips.find((clip) => clip.id === selectedId) ?? null,
    [clips, selectedId],
  )

  useEffect(() => {
    if (!selected) return
    setWordsDirty(false)
    api
      .getClipWords(selected.id)
      .then(setWords)
      .catch(() => setWords([]))
    // 404 is expected for audio-only sources and jobs that never reframed; the
    // player falls back to a centre crop, matching what the renderer does.
    api
      .getCropPath(selected.id)
      .then(setCropPath)
      .catch(() => setCropPath(null))
  }, [selected?.id])

  const patchClip = useCallback((updated: Clip) => {
    setClips((current) => current.map((clip) => (clip.id === updated.id ? updated : clip)))
  }, [])

  const setStatus = async (clip: Clip, status: Clip['status']) => {
    try {
      patchClip(await api.patchClip(clip.id, { status }))
    } catch (err) {
      setError(err as Error)
    }
  }

  const rename = async (clip: Clip, title: string) => {
    try {
      patchClip(await api.patchClip(clip.id, { title }))
    } catch (err) {
      setError(err as Error)
    }
  }

  const commitTrim = async (start: number, end: number) => {
    if (!selected) return
    try {
      patchClip(await api.patchClip(selected.id, { start_s: start, end_s: end }))
      setWords(await api.getClipWords(selected.id))
    } catch (err) {
      setError(err as Error)
    }
  }

  const saveWords = async () => {
    if (!selected) return
    setSavingWords(true)
    try {
      patchClip(await api.patchCaptions(selected.id, { words }))
      setWordsDirty(false)
    } catch (err) {
      setError(err as Error)
    } finally {
      setSavingWords(false)
    }
  }

  const setStyle = async (clip: Clip, styleKey: string) => {
    try {
      patchClip(await api.patchCaptions(clip.id, { caption_style: styleKey }))
    } catch (err) {
      setError(err as Error)
    }
  }

  const setRatio = async (clip: Clip, ratio: string) => {
    try {
      patchClip(await api.patchCaptions(clip.id, { ratio }))
    } catch (err) {
      setError(err as Error)
    }
  }

  const exportClip = async (clip: Clip) => {
    setExporting((current) => new Set(current).add(clip.id))
    setError(null)
    try {
      await api.exportClip(clip.id, clip.ratio, clip.caption_style)
      patchClip(await api.getClip(clip.id))
    } catch (err) {
      setError(err as Error)
    } finally {
      setExporting((current) => {
        const next = new Set(current)
        next.delete(clip.id)
        return next
      })
    }
  }

  const exportKept = async () => {
    const targets = clips.filter((clip) => clip.status === 'kept')
    for (const clip of targets) await exportClip(clip)
  }

  const keptCount = clips.filter((clip) => clip.status === 'kept').length
  const discardedCount = clips.filter((clip) => clip.status === 'discarded').length
  const pendingCount = clips.length - keptCount - discardedCount
  const activeStyle = styles.find((style) => style.key === selected?.caption_style)
  const visibleClips = clips.filter((clip) =>
    filter === 'all' ? true : filter === 'candidate' ? clip.status === 'candidate' || clip.status === 'exported' : clip.status === filter,
  )

  if (error && clips.length === 0 && !job) {
    return (
      <div className="max-w-3xl">
        <ErrorNote error={error} />
      </div>
    )
  }

  if (!job) return <Loading label="Carregando cortes…" />

  return (
    <div>
      <PageHeader
        back={{ to: '/clips', label: 'Cortar vídeo' }}
        eyebrow={<><Icon name="scissors" size={13} /> Revisão de cortes</>}
        title={<span className="line-clamp-2 text-[clamp(1.75rem,3.2vw,2.6rem)]">{job.source?.title || 'Sem título'}</span>}
        actions={
          <>
            <Link to={`/jobs/${job.id}`} className="btn btn-ghost">
              <Icon name="terminal" size={15} />
              Processamento
            </Link>
            <button
              onClick={exportKept}
              disabled={keptCount === 0 || exporting.size > 0}
              className="btn btn-primary"
              title={keptCount === 0 ? 'Aprove pelo menos um corte primeiro' : undefined}
            >
              {exporting.size > 0 ? <Spinner /> : <Icon name="download" size={15} />}
              Exportar aprovados ({keptCount})
            </button>
          </>
        }
      />

      {error && (
        <div className="mt-6 max-w-3xl">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {clips.length === 0 ? (
        <EmptyState
          className="mt-10 max-w-2xl"
          icon="scissors"
          title="A IA não encontrou cortes neste vídeo"
          description="Às vezes o conteúdo não tem trechos que funcionem sozinhos — é uma resposta real, não necessariamente uma falha. Tente um modelo de IA maior, ou aumente a faixa de duração para trechos mais curtos se qualificarem."
          action={<Link to="/clips" className="btn btn-ghost btn-sm">Tentar outro vídeo</Link>}
        />
      ) : (
        <>
          <div className="mt-6 flex flex-wrap items-center gap-2 text-xs text-ink-400">
            <span className="chip"><Icon name="layers" size={12} /> {clips.length} cortes</span>
            <span className="chip text-signal-good"><Icon name="thumbUp" size={12} /> {keptCount} aprovados</span>
            <span className="chip">{pendingCount} para decidir</span>
            <span className="hidden text-ink-500 md:inline">
              · Escolha um corte, ajuste e aprove. Depois exporte os aprovados de uma vez.
            </span>
          </div>

          <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,21rem)_minmax(0,1fr)] 2xl:grid-cols-[minmax(0,21rem)_minmax(0,26rem)_minmax(0,1fr)]">
            {/* Ranked list */}
            <section className="card min-w-0 overflow-hidden lg:sticky lg:top-6">
              <div className="border-b border-ink-800 p-3">
                <Segmented<Filter>
                  ariaLabel="Filtrar cortes"
                  className="w-full"
                  size="sm"
                  value={filter}
                  onChange={setFilter}
                  options={[
                    { value: 'all', label: 'Todos' },
                    { value: 'kept', label: 'Aprovados' },
                    { value: 'candidate', label: 'Pendentes' },
                    { value: 'discarded', label: 'Descartados' },
                  ]}
                />
              </div>
              <ul className="max-h-[70vh] space-y-1 overflow-y-auto p-2">
                {visibleClips.length === 0 && (
                  <li className="px-3 py-8 text-center text-xs text-ink-500">Nenhum corte neste filtro.</li>
                )}
                {visibleClips.map((clip, index) => (
                  <li key={clip.id}>
                    <ClipRow
                      clip={clip}
                      index={index}
                      selected={clip.id === selectedId}
                      onSelect={() => setSelectedId(clip.id)}
                      onKeep={() => setStatus(clip, clip.status === 'kept' ? 'candidate' : 'kept')}
                      onDiscard={() =>
                        setStatus(clip, clip.status === 'discarded' ? 'candidate' : 'discarded')
                      }
                    />
                  </li>
                ))}
              </ul>
            </section>

            {/* Player + trim */}
            {selected && jobId && (
              <section className="card min-w-0 space-y-6 p-4 sm:p-5">
                <ClipPlayer
                  src={api.mediaUrl(jobId)}
                  startS={selected.start_s}
                  endS={selected.end_s}
                  words={words}
                  style={activeStyle}
                  ratio={selected.ratio}
                  cropPath={cropPath}
                />
                <TrimBar
                  words={words}
                  startS={selected.start_s}
                  endS={selected.end_s}
                  originalStart={selected.start_s}
                  originalEnd={selected.end_s}
                  onCommit={commitTrim}
                />
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => setStatus(selected, selected.status === 'discarded' ? 'candidate' : 'discarded')}
                    className={`btn ${selected.status === 'discarded' ? 'btn-ghost text-signal-bad' : 'btn-ghost'}`}
                  >
                    <Icon name={selected.status === 'discarded' ? 'refresh' : 'thumbDown'} size={15} />
                    {selected.status === 'discarded' ? 'Desfazer descarte' : 'Descartar'}
                  </button>
                  <button
                    onClick={() => setStatus(selected, selected.status === 'kept' ? 'candidate' : 'kept')}
                    className={`btn ${selected.status === 'kept' ? 'btn-ghost !border-signal-good/50 text-signal-good' : 'btn-primary'}`}
                  >
                    <Icon name={selected.status === 'kept' ? 'check' : 'thumbUp'} size={15} />
                    {selected.status === 'kept' ? 'Aprovado' : 'Aprovar'}
                  </button>
                </div>
              </section>
            )}

            {/* Editor + style */}
            {selected && (
              <section className="min-w-0 space-y-5 lg:col-span-2 2xl:col-span-1">
                <div className="card overflow-hidden">
                  <div className="border-b border-ink-800 p-3">
                    <Segmented<Tab>
                      ariaLabel="Seções do corte"
                      className="w-full"
                      value={tab}
                      onChange={setTab}
                      options={[
                        { value: 'about', label: 'Sobre', icon: 'info' },
                        { value: 'text', label: 'Legenda', icon: 'captions' },
                        { value: 'look', label: 'Visual', icon: 'type' },
                      ]}
                    />
                  </div>

                  <div className="p-5">
                    {tab === 'about' && (
                      <AboutTab key={selected.id} clip={selected} onRename={(title) => rename(selected, title)} />
                    )}
                    {tab === 'text' && (
                      <CaptionEditor
                        words={words}
                        onChange={(next) => {
                          setWords(next)
                          setWordsDirty(true)
                        }}
                        onSave={saveWords}
                        saving={savingWords}
                        dirty={wordsDirty}
                      />
                    )}
                    {tab === 'look' && (
                      <div className="fade-in space-y-6">
                        <div>
                          <p className="label mb-3">Estilo da legenda</p>
                          <div className="grid gap-2 sm:grid-cols-2">
                            {styles.map((style) => (
                              <StyleCard
                                key={style.key}
                                style={style}
                                active={style.key === selected.caption_style}
                                onSelect={() => setStyle(selected, style.key)}
                              />
                            ))}
                          </div>
                        </div>
                        <div>
                          <p className="label mb-3">Formato</p>
                          <div className="grid grid-cols-3 gap-2">
                            {RATIOS.map((ratio) => {
                              const active = ratio.value === selected.ratio
                              const [w, h] = ratio.value.split(':').map(Number)
                              return (
                                <button
                                  key={ratio.value}
                                  onClick={() => setRatio(selected, ratio.value)}
                                  className={[
                                    'flex flex-col items-center gap-2 rounded-xl border p-3 transition-colors',
                                    active
                                      ? 'border-accent-500/70 bg-accent-500/[0.07]'
                                      : 'border-ink-750 bg-ink-900 hover:border-ink-700',
                                  ].join(' ')}
                                >
                                  <span className="grid h-9 place-items-center">
                                    <span
                                      className={`block rounded-[3px] border-2 ${active ? 'border-accent-400' : 'border-ink-500'}`}
                                      style={{ width: `${(w / Math.max(w, h)) * 30}px`, height: `${(h / Math.max(w, h)) * 30}px` }}
                                    />
                                  </span>
                                  <span className="numeric text-sm font-semibold text-ink-100">{ratio.label}</span>
                                  <span className="text-center text-[10px] leading-tight text-ink-500">{ratio.hint}</span>
                                </button>
                              )
                            })}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <ExportCard
                  clip={selected}
                  styleLabel={activeStyle?.label ?? selected.caption_style}
                  exporting={exporting.has(selected.id)}
                  onExport={() => exportClip(selected)}
                />
              </section>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function AboutTab({ clip, onRename }: { clip: Clip; onRename: (title: string) => void }) {
  const [title, setTitle] = useState(clip.title)
  useEffect(() => setTitle(clip.title), [clip.title])

  return (
    <div className="fade-in space-y-5">
      <div>
        <label htmlFor="clip-title" className="label mb-2">Título do corte</label>
        <input
          id="clip-title"
          className="input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title.trim() && title !== clip.title && onRename(title.trim())}
          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        />
      </div>
      <div className="flex items-center gap-4 rounded-xl bg-ink-900 p-4">
        <ScoreRing score={clip.score} size={52} />
        <div>
          <p className="text-sm font-semibold text-ink-100">Nota da IA: {clip.score}/100</p>
          <p className="text-xs text-ink-500">Quanto maior, mais chance de prender a atenção.</p>
        </div>
      </div>
      <div>
        <p className="label mb-2">Por que este trecho</p>
        <p className="text-sm leading-relaxed text-ink-300">
          {clip.reason || 'A IA não deu uma justificativa para este corte.'}
        </p>
      </div>
      {clip.hook && (
        <div>
          <p className="label mb-2">Gancho</p>
          <p className="border-l-2 border-accent-500 pl-3 font-display text-xl italic leading-snug text-ink-100">
            “{clip.hook}”
          </p>
        </div>
      )}
    </div>
  )
}

function StyleCard({
  style,
  active,
  onSelect,
}: {
  style: CaptionStyle
  active: boolean
  onSelect: () => void
}) {
  const p = style.preview
  return (
    <button
      onClick={onSelect}
      className={[
        'overflow-hidden rounded-xl border text-left transition-colors',
        active ? 'border-accent-500/70 ring-2 ring-accent-500/20' : 'border-ink-750 hover:border-ink-700',
      ].join(' ')}
    >
      <span className="grid h-16 place-items-center bg-gradient-to-br from-ink-700 to-ink-900 px-2">
        <span
          className="text-[15px] leading-none"
          style={{
            fontFamily: p.font === 'Anton' ? 'Anton, Impact, sans-serif' : undefined,
            fontWeight: p.boxed || p.font === 'Anton' ? 400 : 700,
            textTransform: p.allCaps ? 'uppercase' : 'none',
            color: p.primary,
            textShadow: p.boxed ? undefined : '0 0 3px #000, 0 0 6px #000',
            background: p.boxed ? 'rgba(0,0,0,0.78)' : undefined,
            padding: p.boxed ? '0.2em 0.45em' : undefined,
          }}
        >
          Isso <span style={{ color: p.accent ?? undefined }}>muda</span> tudo
        </span>
      </span>
      <span className={`block px-3 py-2.5 ${active ? 'bg-accent-500/[0.07]' : 'bg-ink-900'}`}>
        <span className="flex items-center justify-between gap-2">
          <span className="text-sm font-semibold text-ink-100">{style.label}</span>
          {active && <Icon name="check" size={14} strokeWidth={3} className="text-accent-400" />}
        </span>
        <span className="mt-0.5 block text-[11px] leading-snug text-ink-500">{style.description}</span>
      </span>
    </button>
  )
}

function ExportCard({
  clip,
  styleLabel,
  exporting,
  onExport,
}: {
  clip: Clip
  styleLabel: string
  exporting: boolean
  onExport: () => void
}) {
  return (
    <div className="card p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-ink-100">Exportar este corte</p>
          <p className="numeric mt-0.5 text-xs text-ink-500">
            {clip.ratio} · {styleLabel} · {formatDuration(clip.duration_s)}
          </p>
        </div>
        <button onClick={onExport} disabled={exporting} className="btn btn-primary">
          {exporting ? <><Spinner /> Renderizando…</> : <><Icon name="download" size={15} /> Exportar MP4</>}
        </button>
      </div>

      {clip.exports.length > 0 && (
        <ul className="mt-4 space-y-1.5 border-t border-ink-800 pt-4">
          {clip.exports.map((record) => (
            <li key={record.id}>
              <a
                href={record.download_url}
                download
                className="group flex items-center gap-3 rounded-lg bg-ink-900 px-3 py-2.5 transition-colors hover:bg-ink-800"
              >
                <Icon name="film" size={16} className="text-signal-good" />
                <span className="min-w-0 flex-1 truncate text-sm text-ink-200">
                  {record.ratio} · {record.style}
                </span>
                <span className="numeric text-xs text-ink-500">{formatBytes(record.size_bytes)}</span>
                <Icon name="download" size={15} className="text-ink-500 group-hover:text-accent-400" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ScoreRing({ score, size = 40 }: { score: number; size?: number }) {
  const radius = size / 2 - 3
  const circumference = 2 * Math.PI * radius
  const color = score >= 85 ? 'var(--color-accent-400)' : score >= 70 ? 'var(--color-signal-warn)' : 'var(--color-ink-500)'
  return (
    <span className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--color-ink-800)" strokeWidth="3" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - Math.min(100, Math.max(0, score)) / 100)}
        />
      </svg>
      <span className="numeric absolute text-xs font-bold text-ink-100" style={{ fontSize: size * 0.28 }}>
        {score}
      </span>
    </span>
  )
}

function ClipRow({
  clip,
  index,
  selected,
  onSelect,
  onKeep,
  onDiscard,
}: {
  clip: Clip
  index: number
  selected: boolean
  onSelect: () => void
  onKeep: () => void
  onDiscard: () => void
}) {
  return (
    <div
      className={[
        'rise group flex cursor-pointer items-center gap-3 rounded-xl border p-2.5 transition-colors duration-150',
        selected
          ? 'border-ink-700 bg-ink-800'
          : 'border-transparent hover:bg-ink-800/50',
        clip.status === 'discarded' ? 'opacity-45' : '',
      ].join(' ')}
      style={{ animationDelay: `${Math.min(index, 10) * 30}ms` }}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      aria-current={selected}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onSelect()
      }}
    >
      <ScoreRing score={clip.score} />

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold leading-snug text-ink-100">
          {clip.title || 'Corte sem título'}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="numeric text-xs text-ink-500">{formatDuration(clip.duration_s)}</span>
          {clip.status === 'kept' && <span className="text-[11px] font-semibold text-signal-good">Aprovado</span>}
          {clip.user_trimmed && <span className="text-[11px] text-ink-500">ajustado</span>}
          {clip.exports.length > 0 && <span className="text-[11px] text-accent-400">exportado</span>}
        </div>
      </div>

      <span className="flex shrink-0 gap-0.5">
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDiscard()
          }}
          className={`btn btn-icon btn-danger ${clip.status === 'discarded' ? 'text-signal-bad' : ''}`}
          aria-label={clip.status === 'discarded' ? 'Desfazer descarte' : 'Descartar'}
          title={clip.status === 'discarded' ? 'Desfazer descarte' : 'Descartar'}
        >
          <Icon name={clip.status === 'discarded' ? 'refresh' : 'x'} size={15} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onKeep()
          }}
          className={[
            'btn btn-icon',
            clip.status === 'kept'
              ? 'bg-signal-good/15 text-signal-good'
              : 'btn-quiet hover:!text-signal-good',
          ].join(' ')}
          aria-label={clip.status === 'kept' ? 'Remover aprovação' : 'Aprovar'}
          title={clip.status === 'kept' ? 'Remover aprovação' : 'Aprovar'}
        >
          <Icon name="check" size={15} strokeWidth={2.4} />
        </button>
      </span>
    </div>
  )
}
