import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { api, type SystemStatus } from './api'
import { Icon, type IconName } from './components/Icon'

const NAV: { to: string; label: string; icon: IconName; end?: boolean; hint: string }[] = [
  { to: '/', label: 'Início', icon: 'home', end: true, hint: 'Visão geral' },
  { to: '/clips', label: 'Cortar vídeo', icon: 'scissors', hint: 'Vídeo longo → shorts' },
  { to: '/create', label: 'Criar vídeo', icon: 'sparkles', hint: 'Tema → vídeo narrado' },
  { to: '/settings', label: 'Configurações', icon: 'settings', hint: 'IA, chaves e exportação' },
]

/**
 * Application shell: a slim navigation rail on desktop, a top bar on small
 * screens. Two workflows now live side by side (cutting and creating), so the
 * nav names them outright instead of leaving them to be discovered.
 */
export function App() {
  const [system, setSystem] = useState<SystemStatus | null>(null)
  const location = useLocation()

  useEffect(() => {
    api.system().then(setSystem).catch(() => setSystem(null))
  }, [])

  // Cutting-flow pages (job progress and review) belong under "Cortar vídeo".
  const inClipFlow = location.pathname.startsWith('/jobs')

  return (
    <div className="app-glow min-h-screen bg-ink-900">
      {/* Desktop rail */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-ink-800 bg-ink-950/70 backdrop-blur lg:flex">
        <Brand />
        <nav className="mt-2 flex flex-col gap-1 px-3">
          {NAV.map((item) => (
            <RailLink key={item.to} item={item} forceActive={item.to === '/clips' && inClipFlow} />
          ))}
        </nav>
        <div className="mt-auto p-3">{system && <SystemCard system={system} />}</div>
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-30 border-b border-ink-800 bg-ink-950/85 backdrop-blur lg:hidden">
        <div className="flex items-center justify-between px-4 pt-3">
          <Brand compact />
          {system && <SystemPill system={system} />}
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-2 pt-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                [
                  'flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive || (item.to === '/clips' && inClipFlow)
                    ? 'bg-ink-800 text-ink-100'
                    : 'text-ink-400 hover:text-ink-100',
                ].join(' ')
              }
            >
              <Icon name={item.icon} size={16} />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="min-w-0 overflow-x-clip lg:pl-64">
        <div className="mx-auto max-w-[1440px] px-4 pb-24 pt-8 sm:px-6 lg:px-10 lg:pt-12">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

function Brand({ compact }: { compact?: boolean }) {
  return (
    <NavLink to="/" className={`flex items-center gap-3 ${compact ? '' : 'px-6 pb-6 pt-7'}`}>
      <span className="grid size-9 place-items-center rounded-xl bg-accent-500 text-ink-950 shadow-[0_8px_24px_-10px_var(--color-accent-500)]">
        <Icon name="play" size={16} strokeWidth={0} className="fill-current" />
      </span>
      <span className="font-display text-[1.6rem] leading-none text-ink-100">
        Auto<span className="italic text-accent-500">Clip</span>
      </span>
    </NavLink>
  )
}

function RailLink({
  item,
  forceActive,
}: {
  item: (typeof NAV)[number]
  forceActive?: boolean
}) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) => {
        const active = isActive || forceActive
        return [
          'group relative flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors duration-150',
          active ? 'bg-ink-800/80 text-ink-100' : 'text-ink-400 hover:bg-ink-850 hover:text-ink-100',
        ].join(' ')
      }}
    >
      {({ isActive }) => {
        const active = isActive || forceActive
        return (
          <>
            {active && (
              <span className="absolute -left-3 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-accent-500" />
            )}
            <span
              className={[
                'grid size-8 place-items-center rounded-lg transition-colors',
                active ? 'bg-accent-500/15 text-accent-400' : 'bg-ink-850 text-ink-400 group-hover:text-ink-200',
              ].join(' ')}
            >
              <Icon name={item.icon} size={17} />
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-semibold">{item.label}</span>
              <span className="block text-[11px] text-ink-500">{item.hint}</span>
            </span>
          </>
        )
      }}
    </NavLink>
  )
}

/**
 * Machine status, surfaced permanently: whether ffmpeg can render and whether
 * the GPU is in use are the two things that change how long everything takes.
 */
function SystemCard({ system }: { system: SystemStatus }) {
  const accel = system.accel.toUpperCase()
  return (
    <NavLink
      to="/settings#maquina"
      className="block rounded-xl border border-ink-800 bg-ink-900/80 p-3.5 transition-colors hover:border-ink-700"
    >
      <div className="flex items-center justify-between">
        <span className="eyebrow">Este computador</span>
        <span
          className={`flex items-center gap-1.5 text-[11px] font-semibold ${system.ready ? 'text-signal-good' : 'text-signal-bad'}`}
        >
          <span className={`size-1.5 rounded-full ${system.ready ? 'bg-signal-good' : 'bg-signal-bad'}`} />
          {system.ready ? 'Pronto' : 'Requer ajuste'}
        </span>
      </div>
      <div className="mt-2.5 flex items-center gap-2.5">
        <span className="grid size-8 place-items-center rounded-lg bg-ink-800 text-accent-400">
          <Icon name="cpu" size={16} />
        </span>
        <div className="min-w-0 leading-tight">
          <p className="numeric text-sm font-semibold text-ink-100">{accel}</p>
          <p className="truncate text-[11px] text-ink-500">
            {system.gpu_name ? system.gpu_name.replace('NVIDIA GeForce ', '') : 'Processador (CPU)'}
          </p>
        </div>
      </div>
    </NavLink>
  )
}

function SystemPill({ system }: { system: SystemStatus }) {
  return (
    <span
      className={`chip ${system.ready ? 'text-signal-good' : 'text-signal-bad'}`}
      title={system.ready ? 'Todos os componentes presentes' : 'Rode autoclip doctor'}
    >
      <span className={`size-1.5 rounded-full ${system.ready ? 'bg-signal-good' : 'bg-signal-bad'}`} />
      {system.accel.toUpperCase()}
    </span>
  )
}
