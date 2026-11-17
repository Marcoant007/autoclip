import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import {
  ApiError,
  api,
  formatDuration,
  formatRelative,
  type Job,
  type JobSettingsOverrides,
  type ProviderStatus,
} from '../api'
import { ErrorNote } from '../components/ErrorNote'
import { Icon, Spinner } from '../components/Icon'
import { Callout, EmptyState, Field, PageHeader, Segmented, StatusBadge, Toggle } from '../components/ui'

type SourceMode = 'url' | 'file'

const WHISPER_OPTIONS = [
  { value: '', label: 'Padrão das configurações' },
  { value: 'tiny', label: 'Muito rápido (tiny) — menos preciso' },
  { value: 'base', label: 'Rápido (base)' },
  { value: 'small', label: 'Equilibrado (small)' },
  { value: 'medium', label: 'Preciso (medium)' },
  { value: 'large-v3', label: 'Máxima precisão (large-v3) — mais lento' },
]

export function Ingest() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<SourceMode>('url')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState<SourceMode | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [overrides, setOverrides] = useState<JobSettingsOverrides>({})
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [dragging, setDragging] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.listJobs(10).then(setJobs).catch(() => setJobs([]))
    api.providerStatus().then(setProviders).catch(() => undefined)
  }, [])

  const start = useCallback(
    async (kind: SourceMode, run: () => Promise<{ id: string }>) => {
      setBusy(kind)
      setError(null)
      try {
        const source = await run()
        const job = await api.createJob(source.id, overrides)
        navigate(`/jobs/${job.id}`)
      } catch (err) {
        setError(err as Error)
      } finally {
        setBusy(null)
      }
    },
    [navigate, overrides],
  )

  const submitUrl = (event: React.FormEvent) => {
    event.preventDefault()
    if (!url.trim()) return
    void start('url', () => api.ingestYouTube(url.trim()))
  }

  const submitFile = (file: File) => void start('file', () => api.uploadSource(file))

  const usableProvider = providers.find((p) => p.available)
  const customized = Object.values(overrides).some((value) => value !== undefined)

  return (
    <div>
      <PageHeader
        eyebrow={<><Icon name="scissors" size={13} /> Cortar vídeo</>}
        title={<>Vídeo longo entra. <span className="italic text-accent-500">Shorts</span> saem.</>}
        description="A IA transcreve, encontra os momentos que funcionam sozinhos, enquadra quem está falando no formato vertical e coloca legendas animadas."
      />

      {providers.length > 0 && !usableProvider && (
        <div className="mt-8 max-w-3xl">
          <Callout
            tone="warn"
            title="Nenhum provedor de IA está acessível"
            action={<Link to="/settings" className="btn btn-ghost btn-sm">Configurar</Link>}
          >
            Sem ele a escolha dos cortes vai falhar. Adicione uma chave de API ou inicie o Ollama.
          </Callout>
        </div>
      )}

      <div className="mt-10 grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="card-raised rise min-w-0 p-5 sm:p-7" style={{ animationDelay: '80ms' }}>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="text-base font-semibold text-ink-100">De onde vem o vídeo?</h2>
            <Segmented<SourceMode>
              ariaLabel="Origem do vídeo"
              value={mode}
              onChange={setMode}
              disabled={busy !== null}
              options={[
                { value: 'url', label: 'Link do YouTube', icon: 'link' },
                { value: 'file', label: 'Arquivo', icon: 'upload' },
              ]}
            />
          </div>

          <div className="mt-6">
            {mode === 'url' ? (
              <form onSubmit={submitUrl} className="fade-in">
                <label htmlFor="url" className="sr-only">Link do vídeo</label>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <div className="relative flex-1">
                    <Icon
                      name="link"
                      size={18}
                      className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-500"
                    />
                    <input
                      id="url"
                      className="input !rounded-xl !py-3.5 !pl-11 text-base"
                      placeholder="https://youtube.com/watch?v=…"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      autoComplete="off"
                      spellCheck={false}
                      disabled={busy !== null}
                      autoFocus
                    />
                  </div>
                  <button
                    type="submit"
                    className="btn btn-primary btn-lg shrink-0"
                    disabled={busy !== null || !url.trim()}
                  >
                    {busy === 'url' ? <><Spinner /> Baixando…</> : <><Icon name="wand" size={17} /> Encontrar cortes</>}
                  </button>
                </div>
                <p className="mt-3 flex items-center gap-1.5 text-xs text-ink-500">
                  <Icon name="info" size={13} />
                  Baixe apenas vídeos que você tem direito de usar.
                </p>
              </form>
            ) : (
              <div className="fade-in">
                <div
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDragging(true)
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault()
                    setDragging(false)
                    const file = e.dataTransfer.files[0]
                    if (file && busy === null) submitFile(file)
                  }}
                  className={[
                    'flex min-h-56 cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 text-center transition-colors duration-200',
                    dragging
                      ? 'border-accent-500 bg-accent-500/[0.06]'
                      : 'border-ink-750 bg-ink-900/60 hover:border-ink-600',
                  ].join(' ')}
                  onClick={() => busy === null && fileInput.current?.click()}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') fileInput.current?.click()
                  }}
                >
                  <span className="grid size-14 place-items-center rounded-2xl bg-ink-800 text-accent-400">
                    {busy === 'file' ? <Spinner size={22} /> : <Icon name="upload" size={24} />}
                  </span>
                  <span className="text-base font-semibold text-ink-100">
                    {busy === 'file' ? 'Enviando arquivo…' : 'Arraste o vídeo ou áudio aqui'}
                  </span>
                  <span className="text-sm text-ink-500">
                    ou <span className="link">escolha no computador</span>
                  </span>
                  <span className="mt-1 text-xs text-ink-600">mp4 · mov · mkv · webm · mp3 · wav · m4a</span>
                </div>
                <input
                  ref={fileInput}
                  type="file"
                  className="hidden"
                  accept="video/*,audio/*"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) submitFile(file)
                    e.target.value = ''
                  }}
                />
              </div>
            )}
          </div>

          {error && (
            <div className="mt-5">
              <ErrorNote error={error} onDismiss={() => setError(null)} />
            </div>
          )}

          <AdvancedOptions
            open={advancedOpen}
            onToggle={() => setAdvancedOpen((v) => !v)}
            overrides={overrides}
            onChange={setOverrides}
            providers={providers}
            customized={customized}
          />
        </section>

        <aside className="rise card min-w-0 p-5 sm:p-6" style={{ animationDelay: '140ms' }}>
          <h2 className="text-sm font-semibold text-ink-100">Como funciona</h2>
          <ol className="mt-4 space-y-4">
            {[
              { icon: 'upload' as const, title: 'Envie', text: 'Link do YouTube ou arquivo do seu computador.' },
              { icon: 'captions' as const, title: 'Transcrição', text: 'Cada palavra é transcrita com tempo exato.' },
              { icon: 'wand' as const, title: 'A IA escolhe', text: 'Os trechos com gancho e começo-meio-fim viram cortes.' },
              { icon: 'ratio' as const, title: 'Enquadramento', text: 'A câmera segue quem fala no formato 9:16.' },
              { icon: 'check' as const, title: 'Você revisa', text: 'Aprove, ajuste o início/fim, a legenda e exporte.' },
            ].map((step, index) => (
              <li key={step.title} className="flex gap-3">
                <span className="relative flex flex-col items-center">
                  <span className="grid size-8 place-items-center rounded-lg bg-ink-800 text-accent-400">
                    <Icon name={step.icon} size={15} />
                  </span>
                  {index < 4 && <span className="mt-1 w-px flex-1 bg-ink-800" />}
                </span>
                <span className="pb-1">
                  <span className="block text-sm font-semibold text-ink-200">{step.title}</span>
                  <span className="block text-xs leading-relaxed text-ink-500">{step.text}</span>
                </span>
              </li>
            ))}
          </ol>
        </aside>
      </div>

      <RecentJobs jobs={jobs} />
    </div>
  )
}

function AdvancedOptions({
  open,
  onToggle,
  overrides,
  onChange,
  providers,
  customized,
}: {
  open: boolean
  onToggle: () => void
  overrides: JobSettingsOverrides
  onChange: (next: JobSettingsOverrides) => void
  providers: ProviderStatus[]
  customized: boolean
}) {
  const set = <K extends keyof JobSettingsOverrides>(key: K, value: JobSettingsOverrides[K]) =>
    onChange({ ...overrides, [key]: value })

  return (
    <div className="mt-7 border-t border-ink-800 pt-5">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex flex-1 items-center justify-between gap-4 text-left"
        >
          <span className="flex items-center gap-3">
            <span className="grid size-8 place-items-center rounded-lg bg-ink-800 text-ink-300">
              <Icon name="settings" size={16} />
            </span>
            <span>
              <span className="block text-sm font-semibold text-ink-100">Ajustes deste corte</span>
              <span className="block text-xs text-ink-500">
                {customized ? 'Personalizado para este vídeo' : 'Usando o padrão das Configurações'}
              </span>
            </span>
          </span>
          <Icon
            name="chevronDown"
            size={18}
            className={`order-last text-ink-400 transition-transform duration-300 ${open ? 'rotate-180' : ''}`}
          />
        </button>
        {customized && (
          <button type="button" className="btn btn-quiet btn-sm" onClick={() => onChange({})}>
            Restaurar padrão
          </button>
        )}
      </div>

      <div
        className="grid transition-[grid-template-rows] duration-400 ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="grid gap-x-6 gap-y-5 pt-6 sm:grid-cols-2">
            <Field label="IA que escolhe os cortes" htmlFor="opt-provider">
              <select
                id="opt-provider"
                className="input"
                value={overrides.provider ?? ''}
                onChange={(e) => set('provider', e.target.value || undefined)}
              >
                <option value="">Padrão das configurações</option>
                {providers.map((p) => (
                  <option key={p.name} value={p.name} disabled={!p.available}>
                    {p.available ? p.name : `${p.name} — indisponível`}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Precisão da transcrição" htmlFor="opt-whisper">
              <select
                id="opt-whisper"
                className="input"
                value={overrides.whisper_model ?? ''}
                onChange={(e) => set('whisper_model', e.target.value || undefined)}
              >
                {WHISPER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </Field>
            <NumberField
              label="Quantidade máxima de cortes"
              value={overrides.max_clips}
              placeholder="10"
              min={1}
              max={50}
              onChange={(v) => set('max_clips', v)}
            />
            <div className="grid grid-cols-2 gap-3">
              <NumberField
                label="Duração mín. (s)"
                value={overrides.min_duration_s}
                placeholder="20"
                min={5}
                max={300}
                onChange={(v) => set('min_duration_s', v)}
              />
              <NumberField
                label="Duração máx. (s)"
                value={overrides.max_duration_s}
                placeholder="90"
                min={5}
                max={300}
                onChange={(v) => set('max_duration_s', v)}
              />
            </div>
            <div className="sm:col-span-2">
              <Toggle
                checked={overrides.diarization ?? false}
                onChange={(checked) => set('diarization', checked || undefined)}
                label="Várias pessoas falando"
                description="Identifica quem está falando e corta para essa pessoa no enquadramento."
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function NumberField({
  label,
  value,
  placeholder,
  min,
  max,
  onChange,
}: {
  label: string
  value: number | undefined
  placeholder: string
  min: number
  max: number
  onChange: (value: number | undefined) => void
}) {
  const id = `num-${label}`
  return (
    <Field label={label} htmlFor={id}>
      <input
        id={id}
        type="number"
        className="input numeric"
        placeholder={placeholder}
        value={value ?? ''}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}
      />
    </Field>
  )
}

function RecentJobs({ jobs }: { jobs: Job[] | null }) {
  return (
    <section className="rise mt-14" style={{ animationDelay: '220ms' }}>
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold text-ink-200">Vídeos processados</h2>
        {jobs && jobs.length > 0 && (
          <span className="numeric text-xs text-ink-500">{jobs.length} recentes</span>
        )}
      </div>

      {jobs === null ? (
        <div className="card h-40 animate-pulse" />
      ) : jobs.length === 0 ? (
        <EmptyState
          icon="film"
          title="Nada processado ainda"
          description="Quando você enviar o primeiro vídeo, ele aparece aqui para você voltar aos cortes depois."
        />
      ) : (
        <ul className="card divide-y divide-ink-800/70 overflow-hidden">
          {jobs.map((job) => (
            <li key={job.id}>
              <Link
                to={job.status === 'done' ? `/jobs/${job.id}/clips` : `/jobs/${job.id}`}
                className="group grid grid-cols-[auto_1fr_auto] items-center gap-4 px-4 py-3.5 transition-colors hover:bg-ink-800/40 sm:grid-cols-[auto_1fr_6rem_7rem_auto_auto]"
              >
                <span className="grid size-10 place-items-center rounded-lg bg-ink-800 text-ink-400 group-hover:text-accent-400">
                  <Icon name="film" size={18} />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-ink-100">
                    {job.source?.title || 'Sem título'}
                  </span>
                  <span className="mt-0.5 block text-xs text-ink-500">{formatRelative(job.created_at)}</span>
                </span>
                <span className="numeric hidden text-xs text-ink-400 sm:block">
                  {job.source ? formatDuration(job.source.duration_s) : '—'}
                </span>
                <span className="hidden truncate text-xs text-ink-400 sm:block">{job.provider}</span>
                <StatusBadge status={job.status} progress={job.progress} />
                <Icon name="chevronRight" size={16} className="hidden text-ink-600 group-hover:text-ink-300 sm:block" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
