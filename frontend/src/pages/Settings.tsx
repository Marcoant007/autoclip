import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { api, type ProviderStatus, type Settings as SettingsData, type SystemStatus } from '../api'
import { ErrorNote } from '../components/ErrorNote'
import { Icon, type IconName } from '../components/Icon'
import { Callout, Field, Loading, PageHeader, Segmented, Toggle } from '../components/ui'

const SECRET_LABELS: Record<string, { label: string; hint: string }> = {
  anthropic: { label: 'Anthropic (Claude)', hint: 'console.anthropic.com' },
  openai: { label: 'OpenAI ou compatível', hint: 'Também OpenRouter, Groq, DeepSeek…' },
  gemini: { label: 'Google Gemini', hint: 'aistudio.google.com' },
  huggingface_token: { label: 'HuggingFace', hint: 'Necessário para identificar falantes' },
}

const SECTIONS: { id: string; label: string; icon: IconName }[] = [
  { id: 'ia', label: 'Provedor de IA', icon: 'wand' },
  { id: 'chaves', label: 'Chaves de API', icon: 'key' },
  { id: 'transcricao', label: 'Transcrição', icon: 'captions' },
  { id: 'cortes', label: 'Cortes', icon: 'scissors' },
  { id: 'download', label: 'Download', icon: 'download' },
  { id: 'exportacao', label: 'Exportação', icon: 'film' },
  { id: 'maquina', label: 'Este computador', icon: 'cpu' },
]

const WHISPER_MODELS = [
  { value: 'tiny', label: 'tiny — muito rápido, menos preciso' },
  { value: 'base', label: 'base — rápido' },
  { value: 'small', label: 'small — equilibrado' },
  { value: 'medium', label: 'medium — preciso' },
  { value: 'large-v3', label: 'large-v3 — máxima precisão, mais lento' },
]

export function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [system, setSystem] = useState<SystemStatus | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [saved, setSaved] = useState(false)
  const location = useLocation()

  const reload = () => {
    void api.getSettings().then(setSettings).catch((e) => setError(e as Error))
    void api.providerStatus().then(setProviders).catch(() => undefined)
    void api.system().then(setSystem).catch(() => undefined)
  }

  useEffect(reload, [])

  // Honour deep links such as /settings#maquina once the page has content.
  useEffect(() => {
    if (!settings || !location.hash) return
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [settings, location.hash])

  const patch = async (update: Partial<SettingsData>) => {
    setError(null)
    try {
      setSettings(await api.putSettings(update))
      setSaved(true)
      setTimeout(() => setSaved(false), 1800)
    } catch (err) {
      setError(err as Error)
    }
  }

  if (!settings) {
    return error ? (
      <div className="max-w-3xl"><ErrorNote error={error} /></div>
    ) : (
      <Loading label="Carregando configurações…" />
    )
  }

  const activeProvider = settings.active_provider

  return (
    <div>
      <PageHeader
        eyebrow={<><Icon name="settings" size={13} /> Configurações</>}
        title="Configurações"
        description="As alterações são salvas automaticamente e valem para os próximos vídeos."
      />

      <div className="mt-10 grid items-start gap-8 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <nav className="hidden lg:sticky lg:top-6 lg:block" aria-label="Seções">
          <ul className="space-y-0.5">
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-ink-400 transition-colors hover:bg-ink-850 hover:text-ink-100"
                >
                  <Icon name={section.icon} size={15} />
                  {section.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 max-w-3xl space-y-6">
          {error && <ErrorNote error={error} onDismiss={() => setError(null)} />}

          {settings.insecure_secret_storage && (
            <Callout tone="warn" title="Chaves salvas sem criptografia">
              Não há um cofre de senhas do sistema disponível, então as chaves ficam em texto
              puro no <code className="text-ink-100">config.json</code>. No Linux sem interface,
              instalar um provedor Secret Service ou <code className="text-ink-100">keyrings.alt</code>{' '}
              resolve.
            </Callout>
          )}

          <Section id="ia" icon="wand" title="Provedor de IA" note="Qual modelo escolhe os cortes e escreve os roteiros.">
            <div className="grid gap-2 sm:grid-cols-2">
              {providers.map((provider) => {
                const active = provider.name === activeProvider
                return (
                  <button
                    key={provider.name}
                    onClick={() => patch({ active_provider: provider.name })}
                    className={[
                      'relative rounded-xl border p-4 text-left transition-colors',
                      active
                        ? 'border-accent-500/70 bg-accent-500/[0.07]'
                        : 'border-ink-750 bg-ink-900 hover:border-ink-700',
                    ].join(' ')}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-semibold capitalize text-ink-100">{provider.name}</span>
                      {active ? (
                        <span className="chip !border-accent-600 text-accent-400">Em uso</span>
                      ) : null}
                    </div>
                    <span
                      className={`mt-2 flex items-center gap-1.5 text-xs ${provider.available ? 'text-signal-good' : 'text-ink-500'}`}
                    >
                      <span className={`size-1.5 shrink-0 rounded-full ${provider.available ? 'bg-signal-good' : 'bg-ink-600'}`} />
                      <span className="truncate">
                        {provider.available ? 'Conectado' : provider.detail || 'Indisponível'}
                      </span>
                    </span>
                    {provider.models.length > 0 && (
                      <span className="numeric mt-1.5 block truncate text-[11px] text-ink-600">
                        {provider.models.slice(0, 4).join(' · ')}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>

            <div className="mt-5 grid gap-5 sm:grid-cols-2">
              <TextField
                label={`Modelo (${activeProvider})`}
                value={settings.providers[activeProvider]?.model ?? ''}
                placeholder="nome do modelo"
                onCommit={(value) =>
                  patch({
                    providers: {
                      [activeProvider]: { ...settings.providers[activeProvider], model: value },
                    },
                  })
                }
              />
              <TextField
                label="URL base"
                hint="Para OpenRouter, Groq, DeepSeek ou um servidor local."
                value={settings.providers[activeProvider]?.base_url ?? ''}
                placeholder="https://…"
                onCommit={(value) =>
                  patch({
                    providers: {
                      [activeProvider]: { ...settings.providers[activeProvider], base_url: value || null },
                    },
                  })
                }
              />
            </div>
          </Section>

          <Section id="chaves" icon="key" title="Chaves de API" note="Guardadas no cofre de senhas do sistema. Só são enviadas ao próprio provedor.">
            <div className="divide-y divide-ink-800">
              {Object.entries(SECRET_LABELS).map(([key, meta]) => (
                <SecretField
                  key={key}
                  secretKey={key}
                  label={meta.label}
                  hint={meta.hint}
                  present={settings.keys_present[key] ?? false}
                  onChanged={reload}
                  onError={setError}
                />
              ))}
            </div>
          </Section>

          <Section id="transcricao" icon="captions" title="Transcrição" note="Como a fala é convertida em texto (Whisper).">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Modelo do Whisper" htmlFor="whisper-model">
                <select
                  id="whisper-model"
                  className="input"
                  value={settings.whisper.model}
                  onChange={(e) => patch({ whisper: { ...settings.whisper, model: e.target.value } })}
                >
                  {WHISPER_MODELS.map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </Field>
              <TextField
                label="Idioma"
                hint="Deixe vazio para detectar automaticamente (ex.: pt, en)."
                value={settings.whisper.language}
                placeholder="automático"
                onCommit={(value) => patch({ whisper: { ...settings.whisper, language: value } })}
              />
            </div>
            <div className="mt-5">
              <Toggle
                checked={settings.whisper.diarization}
                disabled={!system?.diarization_available}
                onChange={(checked) => patch({ whisper: { ...settings.whisper, diarization: checked } })}
                label="Identificar quem está falando"
                description={
                  !system?.diarization_available ? (
                    <>
                      Precisa do extra de diarização:{' '}
                      <code className="text-ink-300">uv pip install &apos;autoclip[diarization]&apos;</code>
                    </>
                  ) : (
                    'Útil para podcasts e entrevistas com várias pessoas.'
                  )
                }
              />
            </div>
          </Section>

          <Section id="cortes" icon="scissors" title="Cortes" note="Padrões usados ao cortar um vídeo novo.">
            <div className="grid gap-5 sm:grid-cols-3">
              <NumberField
                label="Duração mínima (s)"
                value={settings.clips.min_duration_s}
                onCommit={(value) => patch({ clips: { ...settings.clips, min_duration_s: value } })}
              />
              <NumberField
                label="Duração máxima (s)"
                value={settings.clips.max_duration_s}
                onCommit={(value) => patch({ clips: { ...settings.clips, max_duration_s: value } })}
              />
              <NumberField
                label="Máximo de cortes"
                value={settings.clips.max_clips}
                onCommit={(value) => patch({ clips: { ...settings.clips, max_clips: value } })}
              />
            </div>
          </Section>

          <Section id="download" icon="download" title="Download do YouTube">
            <Field
              label="Usar cookies do navegador"
              htmlFor="cookies-browser"
              hint="O YouTube bloqueia a maioria dos downloads anônimos. Entre na sua conta nesse navegador e feche-o antes de baixar."
            >
              <select
                id="cookies-browser"
                className="input sm:max-w-xs"
                value={settings.ingest.cookies_from_browser}
                onChange={(e) =>
                  patch({ ingest: { ...settings.ingest, cookies_from_browser: e.target.value } })
                }
              >
                {['', 'chrome', 'firefox', 'edge', 'brave', 'chromium', 'safari'].map((option) => (
                  <option key={option} value={option}>
                    {option === '' ? 'Nenhum' : option.charAt(0).toUpperCase() + option.slice(1)}
                  </option>
                ))}
              </select>
            </Field>
          </Section>

          <Section id="exportacao" icon="film" title="Exportação">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Formato padrão">
                <Segmented
                  ariaLabel="Formato padrão"
                  className="w-full"
                  value={settings.export.ratio}
                  onChange={(value) => patch({ export: { ...settings.export, ratio: value } })}
                  options={[
                    { value: '9:16', label: '9:16' },
                    { value: '1:1', label: '1:1' },
                    { value: '16:9', label: '16:9' },
                  ]}
                />
              </Field>
              <NumberField
                label="Volume alvo (LUFS)"
                hint="-14 é o padrão das redes sociais."
                value={settings.export.loudness_lufs}
                onCommit={(value) => patch({ export: { ...settings.export, loudness_lufs: value } })}
              />
            </div>
            <div className="mt-5 space-y-4">
              <Toggle
                checked={settings.export.prefer_hardware_encoder}
                onChange={(checked) =>
                  patch({ export: { ...settings.export, prefer_hardware_encoder: checked } })
                }
                label="Usar a placa de vídeo para codificar quando possível"
                description={
                  system && !system.nvenc_works
                    ? 'Indisponível neste computador — a exportação usa o processador. Mesma qualidade, mais lento.'
                    : 'Exporta bem mais rápido em placas NVIDIA.'
                }
              />
              <Toggle
                checked={settings.export.write_srt}
                onChange={(checked) => patch({ export: { ...settings.export, write_srt: checked } })}
                label="Gerar também um arquivo de legenda .srt"
              />
            </div>
          </Section>

          {system && (
            <Section id="maquina" icon="cpu" title="Este computador" note="Rode autoclip doctor no terminal para um diagnóstico completo.">
              <dl className="grid gap-2 sm:grid-cols-2">
                <Row label="Sistema" value={system.platform} />
                <Row label="Python" value={system.python_version} />
                <Row label="ffmpeg" value={system.ffmpeg_version ?? 'não encontrado'} ok={!!system.ffmpeg_version} />
                <Row label="Aceleração" value={system.accel.toUpperCase()} />
                <Row label="Dispositivo" value={system.gpu_name ?? '—'} />
                <Row label="Precisão do Whisper" value={system.compute_type} />
                <Row label="Codificação por GPU" value={system.nvenc_works ? 'disponível' : 'indisponível'} ok={system.nvenc_works} />
                <Row label="Legendas (libass)" value={system.has_libass ? 'presente' : 'ausente'} ok={system.has_libass} />
              </dl>
            </Section>
          )}
        </div>
      </div>

      <div
        role="status"
        aria-live="polite"
        className={[
          'fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-xl border border-signal-good/30 bg-ink-850 px-4 py-2.5 text-sm font-semibold text-signal-good shadow-xl transition-all duration-300',
          saved ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-2 opacity-0',
        ].join(' ')}
      >
        <Icon name="check" size={15} strokeWidth={2.6} />
        Salvo
      </div>
    </div>
  )
}

function Section({
  id,
  icon,
  title,
  note,
  children,
}: {
  id: string
  icon: IconName
  title: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className="card rise scroll-mt-24 p-5 sm:p-6">
      <div className="mb-5 flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-ink-800 text-accent-400">
          <Icon name={icon} size={17} />
        </span>
        <div>
          <h2 className="text-base font-semibold text-ink-100">{title}</h2>
          {note && <p className="mt-0.5 text-xs leading-relaxed text-ink-500">{note}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg bg-ink-900 px-3 py-2.5 text-sm">
      <dt className="text-ink-500">{label}</dt>
      <dd
        className={`numeric flex items-center gap-1.5 truncate text-right ${ok === false ? 'text-signal-bad' : 'text-ink-200'}`}
      >
        {ok !== undefined && (
          <span className={`size-1.5 shrink-0 rounded-full ${ok ? 'bg-signal-good' : 'bg-signal-bad'}`} />
        )}
        <span className="truncate">{value}</span>
      </dd>
    </div>
  )
}

/** Commits on blur rather than per keystroke, so a PUT isn't fired per letter. */
function TextField({
  label,
  hint,
  value,
  placeholder,
  onCommit,
}: {
  label: string
  hint?: string
  value: string
  placeholder?: string
  onCommit: (value: string) => void
}) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const id = `text-${label}`

  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <input
        id={id}
        className="input"
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => draft !== value && onCommit(draft)}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        spellCheck={false}
      />
    </Field>
  )
}

function NumberField({
  label,
  hint,
  value,
  onCommit,
}: {
  label: string
  hint?: string
  value: number
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])
  const id = `number-${label}`

  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <input
        id={id}
        type="number"
        className="input numeric"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          const parsed = Number(draft)
          if (!Number.isNaN(parsed) && parsed !== value) onCommit(parsed)
        }}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      />
    </Field>
  )
}

function SecretField({
  secretKey,
  label,
  hint,
  present,
  onChanged,
  onError,
}: {
  secretKey: string
  label: string
  hint: string
  present: boolean
  onChanged: () => void
  onError: (error: Error) => void
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    if (!value.trim()) return
    setBusy(true)
    try {
      await api.putSecret(secretKey, value.trim())
      setValue('')
      onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    try {
      await api.deleteSecret(secretKey)
      onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const id = `secret-${secretKey}`
  return (
    <div className="flex flex-wrap items-center gap-3 py-4 first:pt-0 last:pb-0">
      <div className="w-full sm:w-48">
        <label htmlFor={id} className="block text-sm font-semibold text-ink-100">{label}</label>
        <span className="mt-0.5 flex items-center gap-1.5 text-xs">
          {present ? (
            <span className="flex items-center gap-1 text-signal-good">
              <Icon name="check" size={12} strokeWidth={3} /> Configurada
            </span>
          ) : (
            <span className="text-ink-500">{hint}</span>
          )}
        </span>
      </div>
      <input
        id={id}
        type="password"
        className="input min-w-48 flex-1"
        value={value}
        placeholder={present ? '••••••••••••  (cole para substituir)' : 'Cole a chave aqui'}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && save()}
        autoComplete="off"
      />
      <button onClick={save} disabled={!value.trim() || busy} className="btn btn-ghost">
        Salvar
      </button>
      {present && (
        <button onClick={remove} disabled={busy} className="btn btn-danger btn-icon" aria-label={`Remover chave ${label}`} title="Remover">
          <Icon name="trash" size={15} />
        </button>
      )}
    </div>
  )
}
