import { useEffect, useRef, useState } from 'react'
import { Link, useBlocker, useNavigate, useParams } from 'react-router-dom'

import {
  api,
  formatRelative,
  type Creation,
  type CreationBrief,
  type Storyboard,
  type StoryboardScene,
} from '../api'
import { CreationProduction } from '../components/CreationProduction'
import { ErrorNote } from '../components/ErrorNote'
import { Icon, Spinner, type IconName } from '../components/Icon'
import {
  ChoiceCards,
  EmptyState,
  Field,
  Loading,
  PageHeader,
  ProgressBar,
  Segmented,
  Stepper,
} from '../components/ui'

const nicheLabels: Record<CreationBrief['niche'], string> = {
  biblical: 'Bíblico',
  technology: 'Tecnologia',
  general: 'Outros temas',
}

const NICHES: { value: CreationBrief['niche']; label: string; description: string; icon: IconName }[] = [
  { value: 'biblical', label: 'Bíblico', description: 'Histórias, personagens e reflexões', icon: 'book' },
  { value: 'technology', label: 'Tecnologia', description: 'Conceitos, ferramentas e tendências', icon: 'cpu' },
  { value: 'general', label: 'Outros temas', description: 'Curiosidades, história, dicas…', icon: 'globe' },
]

const VISUAL_STYLES: {
  value: CreationBrief['visual_style']
  label: string
  description: string
  icon: IconName
}[] = [
  { value: 'illustrated', label: 'Cenas ilustradas', description: 'Imagens com movimento de câmera (zoom e pan)', icon: 'image' },
  { value: 'motion_graphics', label: 'Motion graphics', description: 'Textos, formas e diagramas animados', icon: 'shapes' },
]

const DURATIONS = [
  { value: 30, label: '30s' },
  { value: 45, label: '45s' },
  { value: 75, label: '75s' },
  { value: 90, label: '1min30' },
  { value: 120, label: '2 min' },
  { value: 180, label: '3 min' },
]

const EXAMPLES: Record<CreationBrief['niche'], string[]> = {
  biblical: [
    'O que a história de Davi ensina sobre coragem?',
    'Quem foi Rute e por que sua lealdade importa',
    'O significado da parábola do filho pródigo',
  ],
  technology: [
    'Como funciona a inteligência artificial generativa',
    'Computação quântica explicada de forma simples',
    'Por que senhas fortes não bastam mais',
  ],
  general: [
    'Por que o céu é azul?',
    'A história por trás da Torre Eiffel',
    '3 hábitos que melhoram o sono',
  ],
}

const FLOW_STEPS = [
  { label: 'Tema', hint: 'Sobre o que é o vídeo' },
  { label: 'Roteiro e imagens', hint: 'Revise cena por cena' },
  { label: 'Produção', hint: 'Narração, movimento e legendas' },
]

const initialBrief: CreationBrief = {
  topic: '',
  niche: 'general',
  duration_s: 75,
  language: 'pt-BR',
  audience: 'Público geral',
  visual_style: 'illustrated',
  reference_notes: '',
  instructions: '',
}

/** Rough narration pace (≈150 wpm) used for every duration estimate here. */
const WORDS_PER_SECOND = 2.5

function countWords(text: string) {
  return text.trim().split(/\s+/).filter(Boolean).length
}

export function Create() {
  const navigate = useNavigate()
  const [brief, setBrief] = useState(initialBrief)
  const [provider, setProvider] = useState('')
  const [providerNames, setProviderNames] = useState<string[]>([])
  const [recent, setRecent] = useState<Creation[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [historyError, setHistoryError] = useState<Error | null>(null)
  const [moreOpen, setMoreOpen] = useState(false)
  const [dragging, setDragging] = useState(false)
  const importInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let active = true
    api
      .listCreations()
      .then((items) => {
        if (active) setRecent(items)
      })
      .catch((err: Error) => {
        if (active) {
          setHistoryError(err)
          setRecent([])
        }
      })
    api
      .getSettings()
      .then((settings) => {
        if (active) {
          setProviderNames(Object.keys(settings.providers))
          setProvider(settings.active_provider)
        }
      })
      .catch((err: Error) => {
        if (active) setError(err)
      })
    return () => {
      active = false
    }
  }, [])

  function patch<K extends keyof CreationBrief>(key: K, value: CreationBrief[K]) {
    setBrief((current) => ({ ...current, [key]: value }))
  }

  async function generate(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const creation = await api.generateCreation(brief, provider || undefined)
      navigate(`/create/${creation.id}`)
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  async function importScript(file: File) {
    setBusy(true)
    setError(null)
    try {
      if (file.size > 1024 * 1024) throw new Error('Use um arquivo JSON de até 1 MB.')
      const content = JSON.parse(await file.text()) as Partial<Creation>
      if (!content || !content.brief || !content.storyboard) {
        throw new Error('O arquivo precisa conter o tema e as cenas de um roteiro do AutoClip.')
      }
      const creation = await api.importCreation(content.brief, content.storyboard)
      navigate(`/create/${creation.id}`)
    } catch (err) {
      setError(err instanceof SyntaxError ? new Error('O arquivo não contém JSON válido.') : (err as Error))
    } finally {
      setBusy(false)
    }
  }

  const canSubmit = !busy && brief.topic.trim() && brief.audience.trim()

  return (
    <div>
      <PageHeader
        eyebrow={<><Icon name="sparkles" size={13} /> Criar vídeo</>}
        title={<>Uma ideia. <span className="italic text-accent-500">Cena por cena.</span></>}
        description="Descreva o tema e a IA escreve o roteiro com narração e plano visual. Você revisa, adiciona imagens e o AutoClip produz o vídeo vertical narrado."
      />
      <div className="rise mt-6" style={{ animationDelay: '40ms' }}>
        <Stepper steps={FLOW_STEPS} current={0} />
      </div>

      <div className="mt-8 grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <form
          onSubmit={(event) => void generate(event)}
          className="card-raised rise relative min-w-0 overflow-hidden"
          style={{ animationDelay: '80ms' }}
        >
          <fieldset disabled={busy} className="min-w-0 space-y-8 p-5 sm:p-7">
            <FormSection number={1} title="Sobre o que é o vídeo?">
              <label htmlFor="creation-topic" className="sr-only">Tema do vídeo</label>
              <textarea
                id="creation-topic"
                className="input min-h-28 !rounded-xl !p-4 text-lg leading-snug"
                required
                maxLength={300}
                value={brief.topic}
                placeholder="Ex.: O que a história de Davi ensina sobre coragem?"
                onChange={(event) => patch('topic', event.target.value)}
              />
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-xs text-ink-500">Ideias:</span>
                {EXAMPLES[brief.niche].map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => patch('topic', example)}
                    className="chip transition-colors hover:border-accent-600 hover:text-ink-100"
                  >
                    {example}
                  </button>
                ))}
              </div>
            </FormSection>

            <FormSection number={2} title="Nicho">
              <ChoiceCards
                ariaLabel="Nicho"
                value={brief.niche}
                onChange={(value) => patch('niche', value)}
                options={NICHES}
              />
            </FormSection>

            <FormSection number={3} title="Estilo visual">
              <ChoiceCards
                ariaLabel="Estilo visual"
                columns={2}
                value={brief.visual_style}
                onChange={(value) => patch('visual_style', value)}
                options={VISUAL_STYLES}
              />
            </FormSection>

            <FormSection number={4} title="Duração, idioma e público">
              <div className="grid gap-5 lg:grid-cols-2">
                <Field label="Duração desejada" className="lg:col-span-2">
                  <Segmented<number>
                    ariaLabel="Duração desejada"
                    className="w-full"
                    value={brief.duration_s}
                    onChange={(value) => patch('duration_s', value)}
                    options={DURATIONS}
                  />
                </Field>
                <Field label="Idioma da narração">
                  <Segmented<CreationBrief['language']>
                    ariaLabel="Idioma"
                    className="w-full"
                    value={brief.language}
                    onChange={(value) => patch('language', value)}
                    options={[
                      { value: 'pt-BR', label: 'Português' },
                      { value: 'en', label: 'Inglês' },
                      { value: 'es', label: 'Espanhol' },
                    ]}
                  />
                </Field>
                <Field
                  label="Para quem é o vídeo?"
                  htmlFor="creation-audience"
                  hint="Ex.: jovens cristãos, iniciantes em programação, pais de primeira viagem."
                >
                  <input
                    id="creation-audience"
                    className="input"
                    required
                    maxLength={300}
                    value={brief.audience}
                    onChange={(event) => patch('audience', event.target.value)}
                  />
                </Field>
              </div>
            </FormSection>

            <div className="rounded-xl border border-ink-800 bg-ink-900/60">
              <button
                type="button"
                onClick={() => setMoreOpen((v) => !v)}
                aria-expanded={moreOpen}
                className="flex w-full items-center justify-between gap-4 p-4 text-left"
              >
                <span>
                  <span className="block text-sm font-semibold text-ink-100">Mais detalhes</span>
                  <span className="block text-xs text-ink-500">
                    Material de referência, orientações de tom e qual IA usar
                  </span>
                </span>
                <Icon
                  name="chevronDown"
                  size={18}
                  className={`text-ink-400 transition-transform duration-300 ${moreOpen ? 'rotate-180' : ''}`}
                />
              </button>
              {moreOpen && (
                <div className="fade-in space-y-5 border-t border-ink-800 p-4">
                  <Field
                    label="Material de referência"
                    optional
                    htmlFor="creation-references"
                    hint="Cole o conteúdo relevante. Links sozinhos não são abertos nesta etapa."
                  >
                    <textarea
                      id="creation-references"
                      className="input min-h-28"
                      maxLength={6000}
                      value={brief.reference_notes}
                      placeholder="Cole um trecho bíblico, documentação ou fatos que o roteiro deve usar."
                      onChange={(event) => patch('reference_notes', event.target.value)}
                    />
                  </Field>
                  <Field label="Orientações" optional htmlFor="creation-instructions">
                    <textarea
                      id="creation-instructions"
                      className="input min-h-20"
                      maxLength={2000}
                      value={brief.instructions}
                      placeholder="Ex.: tom acolhedor, linguagem simples, sem chamada para seguir o canal."
                      onChange={(event) => patch('instructions', event.target.value)}
                    />
                  </Field>
                  <Field
                    label="IA que escreve o roteiro"
                    htmlFor="creation-provider"
                    hint={<>Usa o modelo e a conexão definidos em <Link to="/settings" className="link">Configurações</Link>.</>}
                  >
                    <select
                      id="creation-provider"
                      className="input"
                      value={provider}
                      onChange={(event) => setProvider(event.target.value)}
                    >
                      <option value="">Usar configuração atual</option>
                      {providerNames.map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  </Field>
                </div>
              )}
            </div>
          </fieldset>

          <div className="flex flex-wrap items-center justify-between gap-4 border-t border-ink-800 bg-ink-900/50 px-5 py-4 sm:px-7">
            <p className="text-xs text-ink-500">
              {brief.topic.trim()
                ? `${nicheLabels[brief.niche]} · ${DURATIONS.find((d) => d.value === brief.duration_s)?.label ?? `${brief.duration_s}s`} · ${VISUAL_STYLES.find((s) => s.value === brief.visual_style)?.label}`
                : 'Escreva o tema para continuar.'}
            </p>
            <button className="btn btn-primary btn-lg" type="submit" disabled={!canSubmit}>
              {busy ? <><Spinner /> Escrevendo roteiro…</> : <><Icon name="sparkles" size={17} /> Gerar roteiro e cenas</>}
            </button>
          </div>

          {error && (
            <div className="px-5 pb-5 sm:px-7">
              <ErrorNote error={error} onDismiss={() => setError(null)} />
            </div>
          )}

          {busy && (
            <div
              role="status"
              className="fade-in absolute inset-0 grid place-items-center bg-ink-900/75 backdrop-blur-[2px]"
            >
              <div className="max-w-xs text-center">
                <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-accent-500/15 text-accent-400">
                  <Spinner size={26} />
                </span>
                <p className="mt-4 text-base font-semibold text-ink-100">Escrevendo seu roteiro…</p>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-400">
                  Aguarde nesta página. Modelos locais podem levar alguns minutos.
                </p>
              </div>
            </div>
          )}
        </form>

        <aside className="rise min-w-0 space-y-6" style={{ animationDelay: '140ms' }}>
          <div className="card p-5">
            <h2 className="text-sm font-semibold text-ink-100">Já tem um roteiro?</h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-500">
              Importe um JSON exportado ou revisado. As imagens precisam ser enviadas novamente.
            </p>
            <div
              role="button"
              tabIndex={0}
              onClick={() => !busy && importInput.current?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') importInput.current?.click()
              }}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                const file = e.dataTransfer.files[0]
                if (file && !busy) void importScript(file)
              }}
              className={[
                'mt-4 flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed p-4 transition-colors',
                dragging ? 'border-accent-500 bg-accent-500/[0.06]' : 'border-ink-750 hover:border-ink-600',
              ].join(' ')}
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-ink-800 text-accent-400">
                <Icon name="fileJson" size={19} />
              </span>
              <span className="text-sm">
                <span className="block font-semibold text-ink-200">Importar roteiro JSON</span>
                <span className="block text-xs text-ink-500">Arraste aqui ou clique para escolher</span>
              </span>
            </div>
            <input
              ref={importInput}
              type="file"
              id="creation-import"
              accept=".json,application/json"
              disabled={busy}
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void importScript(file)
                event.target.value = ''
              }}
            />
          </div>

          <div>
            <div className="mb-3 flex items-center justify-between px-1">
              <h2 className="text-sm font-semibold text-ink-200">Roteiros salvos</h2>
              {recent && recent.length > 0 && (
                <span className="numeric text-xs text-ink-500">{recent.length}</span>
              )}
            </div>
            {historyError && <ErrorNote error={historyError} />}
            {recent === null ? (
              <div className="card h-40 animate-pulse" />
            ) : !historyError && recent.length === 0 ? (
              <EmptyState
                icon="sparkles"
                title="Nenhum roteiro ainda"
                description="Seus roteiros aparecem aqui depois da primeira geração."
              />
            ) : (
              <ul className="card max-h-[60vh] space-y-1 overflow-y-auto p-2">
                {recent.map((creation) => (
                  <li key={creation.id}>
                    <Link
                      to={`/create/${creation.id}`}
                      className="group flex items-center gap-3 rounded-xl p-3 transition-colors hover:bg-ink-800/60"
                    >
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-ink-800 text-ink-400 group-hover:text-accent-400">
                        <Icon name={NICHES.find((n) => n.value === creation.brief.niche)?.icon ?? 'globe'} size={17} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-ink-100">
                          {creation.storyboard.title}
                        </span>
                        <span className="mt-0.5 block text-xs text-ink-500">
                          {creation.storyboard.scenes.length} cenas · {formatRelative(creation.updated_at)}
                        </span>
                      </span>
                      <Icon name="chevronRight" size={16} className="text-ink-600 group-hover:text-ink-300" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

function FormSection({
  number,
  title,
  children,
}: {
  number: number
  title: string
  children: React.ReactNode
}) {
  return (
    <section>
      <h2 className="mb-3 flex items-center gap-2.5 text-sm font-semibold text-ink-100">
        <span className="numeric grid size-6 place-items-center rounded-md bg-ink-800 text-xs text-accent-400">
          {number}
        </span>
        {title}
      </h2>
      {children}
    </section>
  )
}

export function CreationReview() {
  const { creationId } = useParams()
  const [creation, setCreation] = useState<Creation | null>(null)
  const [storyboard, setStoryboard] = useState<Storyboard | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState<number | null>(null)
  const dirty =
    !!creation && !!storyboard && JSON.stringify(creation.storyboard) !== JSON.stringify(storyboard)
  const blocker = useBlocker(dirty || uploading !== null)

  useEffect(() => {
    let active = true
    setCreation(null)
    setStoryboard(null)
    setError(null)
    if (creationId)
      api
        .getCreation(creationId)
        .then((item) => {
          if (active) {
            setCreation(item)
            setStoryboard(item.storyboard)
          }
        })
        .catch((err: Error) => {
          if (active) setError(err)
        })
    return () => {
      active = false
    }
  }, [creationId])

  useEffect(() => {
    if (!dirty) return
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [dirty])

  function patchScene(index: number, patch: Partial<StoryboardScene>) {
    setStoryboard(
      (current) =>
        current && {
          ...current,
          scenes: current.scenes.map((scene, i) => (i === index ? { ...scene, ...patch } : scene)),
        },
    )
  }

  function moveScene(index: number, delta: -1 | 1) {
    setStoryboard((current) => {
      if (!current) return current
      const target = index + delta
      if (target < 0 || target >= current.scenes.length) return current
      const scenes = [...current.scenes]
      ;[scenes[index], scenes[target]] = [scenes[target], scenes[index]]
      return { ...current, scenes }
    })
  }

  async function uploadImage(index: number, file: File) {
    if (!creation) return
    setUploading(index)
    setError(null)
    try {
      const result = await api.uploadCreationImage(creation.id, file)
      patchScene(index, { image_id: result.image_id, media_type: result.media_type })
    } catch (err) {
      setError(err as Error)
    } finally {
      setUploading(null)
    }
  }

  async function save(event?: React.FormEvent) {
    event?.preventDefault()
    if (!creation || !storyboard) return
    setBusy(true)
    setError(null)
    try {
      const clean = (items: string[]) => items.map((item) => item.trim()).filter(Boolean)
      const saved = await api.saveCreation(
        creation.id,
        {
          ...storyboard,
          references: clean(storyboard.references),
          review_notes: clean(storyboard.review_notes),
        },
        creation.revision,
      )
      setCreation(saved)
      setStoryboard(saved.storyboard)
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  if (!creation || !storyboard)
    return error ? (
      <div className="max-w-3xl">
        <Link to="/create" className="mb-6 inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-accent-400">
          <Icon name="arrowLeft" size={15} /> Criar vídeo
        </Link>
        <ErrorNote error={error} />
      </div>
    ) : (
      <Loading label="Carregando roteiro…" />
    )

  const wordCount = storyboard.scenes.reduce((count, scene) => count + countWords(scene.narration), 0)
  const estimatedSeconds = Math.round(wordCount / WORDS_PER_SECOND)
  const target = creation.brief.duration_s
  const offTarget = Math.abs(estimatedSeconds - target) > target * 0.2
  const imagesCount = storyboard.scenes.filter((scene) => scene.image_id).length
  const lines = (value: string) =>
    value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)

  return (
    <form onSubmit={(event) => void save(event)}>
      <PageHeader
        back={{ to: '/create', label: 'Criar vídeo' }}
        eyebrow={
          <>
            <span className="chip normal-case tracking-normal">{nicheLabels[creation.brief.niche]}</span>
            <span className="chip normal-case tracking-normal">
              {creation.brief.visual_style === 'illustrated' ? 'Cenas ilustradas' : 'Motion graphics'}
            </span>
            <span className="chip normal-case tracking-normal numeric">Versão {creation.revision}</span>
          </>
        }
        title={storyboard.title || creation.storyboard.title}
        description={<>Tema: {creation.brief.topic}</>}
      />
      <div className="mt-6">
        <Stepper steps={FLOW_STEPS} current={1} />
      </div>

      {error && (
        <div className="mt-6 max-w-4xl">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <div className="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]">
        {/* Script editor */}
        <fieldset disabled={busy || uploading !== null} className="min-w-0 space-y-5">
          <div className="card space-y-5 p-5 sm:p-6">
            <Field label="Título" htmlFor="storyboard-title">
              <input
                id="storyboard-title"
                className="input text-base font-semibold"
                required
                maxLength={300}
                value={storyboard.title}
                onChange={(event) => setStoryboard({ ...storyboard, title: event.target.value })}
              />
            </Field>
            <Field
              label="Descrição para a postagem"
              htmlFor="storyboard-description"
              hint="Legenda do post no Instagram, TikTok ou YouTube."
            >
              <textarea
                id="storyboard-description"
                className="input min-h-24"
                required
                maxLength={3000}
                value={storyboard.description}
                onChange={(event) => setStoryboard({ ...storyboard, description: event.target.value })}
              />
            </Field>
          </div>

          <div className="flex flex-wrap items-end justify-between gap-3 px-1 pt-3">
            <div>
              <h2 className="text-base font-semibold text-ink-100">Cenas</h2>
              <p className="text-xs text-ink-500">
                Cada cena tem uma fala, uma imagem, GIF ou MP4 e um texto opcional na tela.
              </p>
            </div>
            <span className="chip numeric">
              <Icon name="image" size={12} /> {imagesCount}/{storyboard.scenes.length} com mídia
            </span>
          </div>

          {storyboard.scenes.map((scene, index) => (
            <SceneCard
              key={index}
              index={index}
              total={storyboard.scenes.length}
              scene={scene}
              creationId={creation.id}
              uploading={uploading === index}
              onChange={(patch) => patchScene(index, patch)}
              onUpload={(file) => void uploadImage(index, file)}
              onMove={(delta) => moveScene(index, delta)}
              onRemove={() =>
                setStoryboard({ ...storyboard, scenes: storyboard.scenes.filter((_, i) => i !== index) })
              }
            />
          ))}

          <button
            type="button"
            className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-ink-750 py-5 text-sm font-semibold text-ink-400 transition-colors hover:border-accent-600 hover:text-accent-400 disabled:cursor-not-allowed disabled:opacity-40"
            disabled={storyboard.scenes.length >= 12}
            onClick={() =>
              setStoryboard({
                ...storyboard,
                scenes: [...storyboard.scenes, { narration: '', visual_description: '', on_screen_text: '' }],
              })
            }
          >
            <Icon name="plus" size={17} />
            {storyboard.scenes.length >= 12 ? 'Limite de 12 cenas atingido' : 'Adicionar cena'}
          </button>

          <div className="card grid gap-5 p-5 sm:p-6 xl:grid-cols-2">
            <Field
              label="Referências para conferir"
              htmlFor="storyboard-references"
              hint="Uma por linha, até 20. São sugestões da IA — confira fontes e afirmações antes de publicar."
            >
              <textarea
                id="storyboard-references"
                className="input min-h-32"
                value={storyboard.references.join('\n')}
                onChange={(event) => setStoryboard({ ...storyboard, references: event.target.value.split('\n') })}
                onBlur={() =>
                  setStoryboard(
                    (current) => current && { ...current, references: lines(current.references.join('\n')) },
                  )
                }
              />
            </Field>
            <Field label="Notas de revisão" htmlFor="storyboard-notes" hint="Uma por linha, até 20 notas.">
              <textarea
                id="storyboard-notes"
                className="input min-h-32"
                value={storyboard.review_notes.join('\n')}
                onChange={(event) => setStoryboard({ ...storyboard, review_notes: event.target.value.split('\n') })}
                onBlur={() =>
                  setStoryboard(
                    (current) => current && { ...current, review_notes: lines(current.review_notes.join('\n')) },
                  )
                }
              />
            </Field>
          </div>
          <p className="px-1 text-xs leading-relaxed text-ink-500">
            As descrições visuais orientam a escolha das imagens; ainda não são convertidas
            automaticamente em ilustrações por IA.
          </p>
        </fieldset>

        {/* Sidebar */}
        <aside className="min-w-0 space-y-5 lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto lg:pb-2">
          <div className="card p-5">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-semibold text-ink-100">Resumo</p>
              <span
                role="status"
                className={`flex items-center gap-1.5 text-xs font-semibold ${dirty ? 'text-signal-warn' : 'text-signal-good'}`}
              >
                <span className={`size-1.5 rounded-full ${dirty ? 'bg-signal-warn' : 'bg-signal-good'}`} />
                {dirty ? 'Alterações não salvas' : 'Tudo salvo'}
              </span>
            </div>

            <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
              {[
                { label: 'cenas', value: storyboard.scenes.length },
                { label: 'palavras', value: wordCount },
                { label: 'imagens', value: imagesCount },
              ].map((stat) => (
                <div key={stat.label} className="rounded-xl bg-ink-900 px-2 py-3">
                  <dd className="numeric text-xl font-semibold text-ink-100">{stat.value}</dd>
                  <dt className="text-[11px] text-ink-500">{stat.label}</dt>
                </div>
              ))}
            </dl>

            <div className="mt-4">
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-ink-400">Duração estimada da narração</span>
                <span className={`numeric font-semibold ${offTarget ? 'text-signal-warn' : 'text-ink-100'}`}>
                  ≈ {estimatedSeconds}s <span className="font-normal text-ink-500">/ meta {target}s</span>
                </span>
              </div>
              <ProgressBar
                value={estimatedSeconds / target}
                tone={offTarget ? 'muted' : 'good'}
                className="mt-2"
              />
              {offTarget ? (
                <p className="mt-2 text-xs leading-relaxed text-signal-warn">
                  {estimatedSeconds > target
                    ? 'A narração está longa para a meta. Encurte algumas falas.'
                    : 'A narração está curta para a meta. Desenvolva algumas falas.'}
                </p>
              ) : (
                <p className="mt-2 text-xs text-ink-500">
                  Estimativa a 150 palavras/min. O tempo final depende da voz e das pausas.
                </p>
              )}
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              <button
                type="submit"
                className="btn btn-primary flex-1"
                disabled={busy || !dirty || uploading !== null}
              >
                {busy ? <Spinner /> : <Icon name="save" size={15} />}
                {busy ? 'Salvando…' : 'Salvar'}
              </button>
              {!dirty && !busy ? (
                <a className="btn btn-ghost" href={api.creationDownloadUrl(creation.id)} title="Baixar roteiro JSON">
                  <Icon name="download" size={15} />
                  JSON
                </a>
              ) : null}
            </div>
          </div>

          <CreationProduction
            key={creation.id}
            creation={creation}
            disabled={dirty || busy || uploading !== null}
          />
        </aside>
      </div>

      {/* Floating save bar, only while there is something to save. */}
      {dirty && (
        <div className="pointer-events-none sticky bottom-4 z-20 mt-6 flex justify-center">
          <div className="fade-in pointer-events-auto flex items-center gap-4 rounded-2xl border border-ink-700 bg-ink-850/95 py-2.5 pl-5 pr-2.5 shadow-[0_20px_50px_-20px_rgb(0_0_0/0.9)] backdrop-blur">
            <span className="flex items-center gap-2 text-sm text-ink-200">
              <span className="size-2 rounded-full bg-signal-warn" />
              Você tem alterações não salvas
            </span>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy || uploading !== null}
            >
              {busy ? <Spinner /> : <Icon name="save" size={15} />}
              {busy ? 'Salvando…' : 'Salvar agora'}
            </button>
          </div>
        </div>
      )}

      {blocker.state === 'blocked' && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="leave-title"
          className="fade-in fixed inset-0 z-50 grid place-items-center bg-ink-950/70 p-4 backdrop-blur-sm"
        >
          <div className="card-raised w-full max-w-md p-6">
            <span className="grid size-11 place-items-center rounded-xl bg-signal-warn/15 text-signal-warn">
              <Icon name="alert" size={20} />
            </span>
            <h2 id="leave-title" className="mt-4 text-lg font-semibold text-ink-100">
              Sair sem salvar?
            </h2>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-400">
              {uploading !== null
                ? 'Uma imagem ainda está sendo enviada.'
                : 'Você tem alterações no roteiro que ainda não foram salvas.'}
            </p>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => blocker.proceed()}>
                Sair sem salvar
              </button>
              <button type="button" className="btn btn-primary" onClick={() => blocker.reset()}>
                Continuar editando
              </button>
            </div>
          </div>
        </div>
      )}
    </form>
  )
}

function SceneCard({
  index,
  total,
  scene,
  creationId,
  uploading,
  onChange,
  onUpload,
  onMove,
  onRemove,
}: {
  index: number
  total: number
  scene: StoryboardScene
  creationId: string
  uploading: boolean
  onChange: (patch: Partial<StoryboardScene>) => void
  onUpload: (file: File) => void
  onMove: (delta: -1 | 1) => void
  onRemove: () => void
}) {
  const words = countWords(scene.narration)
  const seconds = Math.round(words / WORDS_PER_SECOND)
  const label = String(index + 1).padStart(2, '0')

  return (
    <section className="card p-4 sm:p-5" aria-label={`Cena ${index + 1}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="numeric grid size-9 place-items-center rounded-lg bg-accent-500/15 font-display text-lg text-accent-400">
            {label}
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-ink-100">Cena {index + 1}</p>
            <p className="numeric text-xs text-ink-500">
              ≈ {seconds}s · {words} palavras
            </p>
          </div>
        </div>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            className="btn btn-quiet btn-icon"
            disabled={index === 0}
            onClick={() => onMove(-1)}
            aria-label={`Mover cena ${index + 1} para cima`}
            title="Mover para cima"
          >
            <Icon name="arrowUp" size={15} />
          </button>
          <button
            type="button"
            className="btn btn-quiet btn-icon"
            disabled={index === total - 1}
            onClick={() => onMove(1)}
            aria-label={`Mover cena ${index + 1} para baixo`}
            title="Mover para baixo"
          >
            <Icon name="arrowDown" size={15} />
          </button>
          <button
            type="button"
            className="btn btn-danger btn-icon"
            disabled={total <= 3}
            onClick={onRemove}
            aria-label={`Remover cena ${index + 1}`}
            title={total <= 3 ? 'Um roteiro precisa de pelo menos 3 cenas' : 'Remover cena'}
          >
            <Icon name="trash" size={15} />
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-5 sm:grid-cols-[8.5rem_minmax(0,1fr)]">
        <ImageSlot
          index={index}
          creationId={creationId}
          imageId={scene.image_id ?? null}
          mediaType={scene.media_type ?? 'image'}
          uploading={uploading}
          onUpload={onUpload}
          onClear={() => onChange({ image_id: null, media_type: 'image' })}
          overlay={scene.on_screen_text}
        />

        <div className="min-w-0 space-y-4">
          <Field
            label={<span className="flex items-center gap-1.5"><Icon name="mic" size={14} className="text-accent-400" /> Narração</span>}
            htmlFor={`narration-${index}`}
          >
            <textarea
              id={`narration-${index}`}
              className="input min-h-28 text-[0.9375rem] leading-relaxed"
              required
              maxLength={3000}
              value={scene.narration}
              placeholder="O que a voz vai falar nesta cena…"
              onChange={(event) => onChange({ narration: event.target.value })}
            />
          </Field>
          <div className="grid gap-4 xl:grid-cols-2">
            <Field
              label={<span className="flex items-center gap-1.5"><Icon name="eye" size={14} className="text-ink-400" /> Descrição visual e movimento</span>}
              htmlFor={`visual-${index}`}
            >
              <textarea
                id={`visual-${index}`}
                className="input min-h-24"
                required
                maxLength={3000}
                value={scene.visual_description}
                placeholder="O que aparece na imagem e como a câmera se move…"
                onChange={(event) => onChange({ visual_description: event.target.value })}
              />
            </Field>
            <Field
              label={<span className="flex items-center gap-1.5"><Icon name="type" size={14} className="text-ink-400" /> Texto na tela</span>}
              optional
              htmlFor={`overlay-${index}`}
              hint="Frase curta em destaque sobre a imagem."
            >
              <input
                id={`overlay-${index}`}
                className="input"
                maxLength={200}
                value={scene.on_screen_text}
                onChange={(event) => onChange({ on_screen_text: event.target.value })}
              />
            </Field>
          </div>
        </div>
      </div>
    </section>
  )
}

function ImageSlot({
  index,
  creationId,
  imageId,
  mediaType,
  uploading,
  onUpload,
  onClear,
  overlay,
}: {
  index: number
  creationId: string
  imageId: string | null
  mediaType: 'image' | 'video'
  uploading: boolean
  onUpload: (file: File) => void
  onClear: () => void
  overlay: string
}) {
  const [dragging, setDragging] = useState(false)
  const inputId = `scene-image-${index}`

  return (
    <div>
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
          if (file && !uploading) onUpload(file)
        }}
        className={[
          'group relative mx-auto aspect-[9/16] w-full max-w-[9rem] overflow-hidden rounded-xl border transition-colors',
          dragging ? 'border-accent-500' : imageId ? 'border-ink-750' : 'border-dashed border-ink-700',
        ].join(' ')}
      >
        {imageId ? (
          <>
            {mediaType === 'video' ? (
              <video
                key={imageId}
                src={api.creationImageUrl(creationId, imageId)}
                poster={`${api.creationImageUrl(creationId, imageId)}?poster=true`}
                aria-label={`Animação da cena ${index + 1}`}
                className="size-full object-cover"
                autoPlay
                muted
                loop
                playsInline
              />
            ) : (
              <img
                src={api.creationImageUrl(creationId, imageId)}
                alt={`Imagem da cena ${index + 1}`}
                className="size-full object-cover"
              />
            )}
            {overlay && (
              <span className="absolute inset-x-2 top-1/3 text-center text-[10px] font-bold uppercase leading-tight text-white [text-shadow:0_1px_4px_#000]">
                {overlay}
              </span>
            )}
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-950/70 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
              <label htmlFor={inputId} className="btn btn-ghost btn-sm cursor-pointer">
                <Icon name="refresh" size={13} /> Trocar
              </label>
              <button type="button" className="btn btn-quiet btn-sm" onClick={onClear}>
                <Icon name="x" size={13} /> Remover
              </button>
            </div>
          </>
        ) : (
          <label
            htmlFor={inputId}
            className={[
              'flex size-full cursor-pointer flex-col items-center justify-center gap-2 p-3 text-center transition-colors',
              dragging ? 'bg-accent-500/[0.08]' : 'bg-gradient-to-b from-ink-850 to-ink-900 hover:from-ink-800',
            ].join(' ')}
          >
            <span className="grid size-9 place-items-center rounded-lg bg-ink-800 text-ink-300 group-hover:text-accent-400">
              <Icon name="image" size={17} />
            </span>
            <span className="text-xs font-semibold text-ink-200">Adicionar mídia</span>
            <span className="text-[10px] leading-snug text-ink-500">ou fica uma cartela animada</span>
          </label>
        )}
        {uploading && (
          <div className="absolute inset-0 grid place-items-center bg-ink-950/80">
            <span className="flex flex-col items-center gap-2 text-xs text-ink-200">
              <Spinner size={20} className="text-accent-400" />
              Enviando…
            </span>
          </div>
        )}
      </div>
      <input
        id={inputId}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif,video/mp4,.gif,.mp4"
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onUpload(file)
          event.target.value = ''
        }}
      />
      <p className="mt-2 text-center text-[10px] text-ink-600">
        Imagens estáticas · até 15 MB<br />GIF, WebP animado e MP4 · até 50 MB / 3 min<br />
        Vídeos repetem até o fim da fala, sem áudio original.
      </p>
    </div>
  )
}

