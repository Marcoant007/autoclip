import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, formatDuration, formatRelative, type Creation, type Job, type ProviderStatus, type SystemStatus } from '../api'
import { Icon, type IconName } from '../components/Icon'
import { Callout, EmptyState, StatusBadge } from '../components/ui'

const NICHE_LABELS: Record<string, string> = {
  biblical: 'Bíblico',
  technology: 'Tecnologia',
  general: 'Outros temas',
}

export function Home() {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [creations, setCreations] = useState<Creation[] | null>(null)
  const [providers, setProviders] = useState<ProviderStatus[] | null>(null)
  const [system, setSystem] = useState<SystemStatus | null>(null)

  useEffect(() => {
    api.listJobs(6).then(setJobs).catch(() => setJobs([]))
    api.listCreations().then(setCreations).catch(() => setCreations([]))
    api.providerStatus().then(setProviders).catch(() => setProviders([]))
    api.system().then(setSystem).catch(() => undefined)
  }, [])

  const noProvider = providers !== null && providers.length > 0 && !providers.some((p) => p.available)

  return (
    <div>
      <section className="rise">
        <p className="eyebrow">Estúdio local · Sem contas · Sem marca d&apos;água</p>
        <h1 className="mt-4 max-w-4xl font-display text-[clamp(2.5rem,6vw,4.75rem)] leading-[0.98] text-ink-100">
          O que vamos <span className="italic text-accent-500">produzir</span> hoje?
        </h1>
        <p className="mt-4 max-w-2xl text-[0.9375rem] leading-relaxed text-ink-400">
          Transforme vídeos longos em cortes verticais prontos para postar, ou crie um vídeo
          narrado do zero a partir de um tema.
        </p>
      </section>

      {(noProvider || (system && !system.ready)) && (
        <div className="rise mt-8 max-w-3xl space-y-3" style={{ animationDelay: '60ms' }}>
          {noProvider && (
            <Callout
              tone="warn"
              title="Nenhum provedor de IA disponível"
              action={<Link to="/settings" className="btn btn-ghost btn-sm">Configurar</Link>}
            >
              Adicione uma chave de API ou inicie o Ollama para que a IA escolha os cortes e
              escreva roteiros.
            </Callout>
          )}
          {system && !system.ready && (
            <Callout
              tone="bad"
              title="Faltam componentes neste computador"
              action={<Link to="/settings#maquina" className="btn btn-ghost btn-sm">Ver detalhes</Link>}
            >
              Rode <code className="text-ink-100">autoclip doctor</code> no terminal para ver o
              que corrigir.
            </Callout>
          )}
        </div>
      )}

      <section className="mt-10 grid gap-5 lg:grid-cols-2">
        <ActionCard
          to="/clips"
          icon="scissors"
          delay={80}
          title="Cortar um vídeo longo"
          description="Cole um link do YouTube ou envie um arquivo. A IA encontra os melhores momentos e entrega cortes 9:16 com legendas."
          steps={['Envie o vídeo', 'A IA escolhe os trechos', 'Revise e exporte']}
          cta="Começar cortes"
        />
        <ActionCard
          to="/create"
          icon="sparkles"
          delay={140}
          title="Criar vídeo do zero"
          description="Descreva um tema. A IA escreve o roteiro cena por cena, e o AutoClip produz o vídeo com narração, movimento e legendas."
          steps={['Defina o tema', 'Revise roteiro e imagens', 'Gere o MP4 narrado']}
          cta="Criar vídeo"
          featured
        />
      </section>

      <section className="mt-14 grid gap-8 xl:grid-cols-2">
        <RecentList
          title="Cortes recentes"
          icon="scissors"
          seeAll="/clips"
          loading={jobs === null}
          empty={
            <EmptyState
              icon="film"
              title="Nenhum vídeo cortado ainda"
              description="Seus processamentos aparecem aqui."
              action={<Link to="/clips" className="btn btn-ghost btn-sm">Cortar primeiro vídeo</Link>}
            />
          }
        >
          {jobs?.map((job) => (
            <Link
              key={job.id}
              to={job.status === 'done' ? `/jobs/${job.id}/clips` : `/jobs/${job.id}`}
              className="group flex items-center gap-4 rounded-xl px-3 py-3 transition-colors hover:bg-ink-850"
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-ink-800 text-ink-400 group-hover:text-accent-400">
                <Icon name="film" size={18} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-ink-100">
                  {job.source?.title || 'Sem título'}
                </span>
                <span className="numeric mt-0.5 block text-xs text-ink-500">
                  {job.source ? formatDuration(job.source.duration_s) : '—'} · {job.provider} ·{' '}
                  {formatRelative(job.created_at)}
                </span>
              </span>
              <StatusBadge status={job.status} progress={job.progress} />
            </Link>
          ))}
        </RecentList>

        <RecentList
          title="Roteiros recentes"
          icon="sparkles"
          seeAll="/create"
          loading={creations === null}
          empty={
            <EmptyState
              icon="fileJson"
              title="Nenhum roteiro criado ainda"
              description="Gere seu primeiro vídeo a partir de um tema."
              action={<Link to="/create" className="btn btn-ghost btn-sm">Criar roteiro</Link>}
            />
          }
        >
          {creations?.slice(0, 6).map((creation) => (
            <Link
              key={creation.id}
              to={`/create/${creation.id}`}
              className="group flex items-center gap-4 rounded-xl px-3 py-3 transition-colors hover:bg-ink-850"
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-ink-800 text-ink-400 group-hover:text-accent-400">
                <Icon name="sparkles" size={18} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-ink-100">
                  {creation.storyboard.title}
                </span>
                <span className="mt-0.5 block text-xs text-ink-500">
                  {NICHE_LABELS[creation.brief.niche] ?? creation.brief.niche} ·{' '}
                  {creation.storyboard.scenes.length} cenas · {formatRelative(creation.updated_at)}
                </span>
              </span>
              <Icon name="chevronRight" size={16} className="text-ink-600 group-hover:text-ink-300" />
            </Link>
          ))}
        </RecentList>
      </section>
    </div>
  )
}

function ActionCard({
  to,
  icon,
  title,
  description,
  steps,
  cta,
  featured,
  delay,
}: {
  to: string
  icon: IconName
  title: string
  description: string
  steps: string[]
  cta: string
  featured?: boolean
  delay: number
}) {
  return (
    <Link
      to={to}
      style={{ animationDelay: `${delay}ms` }}
      className={[
        'rise group relative flex flex-col overflow-hidden rounded-2xl border p-6 transition-all duration-300 sm:p-7',
        featured
          ? 'border-accent-600/50 bg-gradient-to-br from-accent-900/70 via-ink-850 to-ink-850 hover:border-accent-500/70'
          : 'border-ink-800 bg-ink-850/80 hover:border-ink-700',
        'hover:-translate-y-0.5 hover:shadow-[0_24px_48px_-28px_rgb(0_0_0/0.8)]',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-4">
        <span
          className={[
            'grid size-12 place-items-center rounded-xl',
            featured ? 'bg-accent-500 text-ink-950' : 'bg-ink-800 text-accent-400',
          ].join(' ')}
        >
          <Icon name={icon} size={22} />
        </span>
        <span className="grid size-9 place-items-center rounded-full border border-ink-750 text-ink-400 transition-all duration-300 group-hover:translate-x-0.5 group-hover:border-accent-500 group-hover:text-accent-400">
          <Icon name="arrowRight" size={16} />
        </span>
      </div>
      <h2 className="mt-6 font-display text-3xl leading-tight text-ink-100">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-ink-400">{description}</p>
      <ol className="mt-6 flex flex-wrap gap-2">
        {steps.map((step, index) => (
          <li key={step} className="chip">
            <span className="numeric text-accent-400">{index + 1}</span>
            {step}
          </li>
        ))}
      </ol>
      <span
        className={`btn mt-7 self-start ${featured ? 'btn-primary' : 'btn-ghost'}`}
      >
        {cta}
        <Icon name="arrowRight" size={15} />
      </span>
    </Link>
  )
}

function RecentList({
  title,
  icon,
  seeAll,
  loading,
  empty,
  children,
}: {
  title: string
  icon: IconName
  seeAll: string
  loading: boolean
  empty: React.ReactNode
  children: React.ReactNode
}) {
  const items = Array.isArray(children) ? children : children ? [children] : []
  return (
    <div className="rise" style={{ animationDelay: '200ms' }}>
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-ink-200">
          <Icon name={icon} size={16} className="text-ink-500" />
          {title}
        </h2>
        <Link to={seeAll} className="text-xs text-ink-500 transition-colors hover:text-accent-400">
          Abrir
        </Link>
      </div>
      {loading ? (
        <div className="card space-y-2 p-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl bg-ink-850" />
          ))}
        </div>
      ) : items.length === 0 ? (
        empty
      ) : (
        <div className="card divide-y divide-ink-800/60 p-2">{children}</div>
      )}
    </div>
  )
}
