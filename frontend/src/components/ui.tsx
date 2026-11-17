import { Link } from 'react-router-dom'

import type { JobStatus } from '../api'
import { Icon, Spinner, type IconName } from './Icon'

/** Title block shared by every page: optional back link, eyebrow, title, actions. */
export function PageHeader({
  back,
  eyebrow,
  title,
  description,
  actions,
}: {
  back?: { to: string; label: string }
  eyebrow?: React.ReactNode
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <header className="rise flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
      <div className="min-w-0 max-w-3xl">
        {back && (
          <Link
            to={back.to}
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-400 transition-colors hover:text-accent-400"
          >
            <Icon name="arrowLeft" size={15} />
            {back.label}
          </Link>
        )}
        {eyebrow && <div className="eyebrow mb-3 flex flex-wrap items-center gap-2">{eyebrow}</div>}
        <h1 className="font-display text-[clamp(2rem,4.2vw,3.25rem)] leading-[1.02] text-ink-100">
          {title}
        </h1>
        {description && (
          <div className="mt-3 max-w-2xl text-[0.9375rem] leading-relaxed text-ink-400">
            {description}
          </div>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-3">{actions}</div>}
    </header>
  )
}

/** Label + control + hint, stacked. */
export function Field({
  label,
  htmlFor,
  hint,
  optional,
  children,
  className = '',
}: {
  label: React.ReactNode
  htmlFor?: string
  hint?: React.ReactNode
  optional?: boolean
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="label mb-2 flex items-baseline gap-2">
        {label}
        {optional && <span className="text-xs font-normal text-ink-500">opcional</span>}
      </label>
      {children}
      {hint && <p className="mt-1.5 text-xs leading-relaxed text-ink-500">{hint}</p>}
    </div>
  )
}

/** Pill-style single choice for small option sets. */
export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  disabled,
  ariaLabel,
  className = '',
  size = 'md',
}: {
  value: T
  options: { value: T; label: React.ReactNode; icon?: IconName; title?: string }[]
  size?: 'sm' | 'md'
  onChange: (value: T) => void
  disabled?: boolean
  ariaLabel?: string
  className?: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={`inline-flex max-w-full gap-1 overflow-x-auto rounded-xl border border-ink-750 bg-ink-900 p-1 ${className}`}
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={String(option.value)}
            type="button"
            role="radio"
            aria-checked={active}
            title={option.title}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={[
              size === 'sm' ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-[0.8125rem]',
              'inline-flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50',
              active
                ? 'bg-ink-750 text-ink-100 shadow-[inset_0_0_0_1px_var(--color-ink-700)]'
                : 'text-ink-400 hover:text-ink-100',
            ].join(' ')}
          >
            {option.icon && (
              <Icon name={option.icon} size={15} className={active ? 'text-accent-400' : ''} />
            )}
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/** Large selectable cards — for choices that deserve a sentence of explanation. */
export function ChoiceCards<T extends string>({
  value,
  options,
  onChange,
  disabled,
  ariaLabel,
  columns = 3,
}: {
  value: T
  options: { value: T; label: string; description?: string; icon?: IconName }[]
  onChange: (value: T) => void
  disabled?: boolean
  ariaLabel?: string
  columns?: 2 | 3
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={`grid gap-3 ${columns === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={[
              'group relative flex items-start gap-3 rounded-xl border p-3.5 text-left transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50',
              active
                ? 'border-accent-500/70 bg-accent-500/[0.07] shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-accent-500)_14%,transparent)]'
                : 'border-ink-750 bg-ink-900 hover:border-ink-700 hover:bg-ink-850',
            ].join(' ')}
          >
            {option.icon && (
              <span
                className={[
                  'grid size-9 shrink-0 place-items-center rounded-lg transition-colors',
                  active ? 'bg-accent-500 text-ink-950' : 'bg-ink-800 text-ink-300 group-hover:text-ink-100',
                ].join(' ')}
              >
                <Icon name={option.icon} size={18} />
              </span>
            )}
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-ink-100">{option.label}</span>
              {option.description && (
                <span className="mt-0.5 block text-xs leading-snug text-ink-500">
                  {option.description}
                </span>
              )}
            </span>
            {active && (
              <span className="absolute right-2.5 top-2.5 grid size-4 place-items-center rounded-full bg-accent-500 text-ink-950">
                <Icon name="check" size={11} strokeWidth={3} />
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

/** Accessible on/off switch with a label to its right. */
export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: React.ReactNode
  description?: React.ReactNode
  disabled?: boolean
}) {
  return (
    <label
      className={`flex items-start gap-3 ${disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
    >
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input
          type="checkbox"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="h-5 w-9 rounded-full bg-ink-750 transition-colors duration-200 peer-checked:bg-accent-500 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent-500" />
        <span className="absolute left-0.5 top-0.5 size-4 rounded-full bg-ink-200 transition-transform duration-200 peer-checked:translate-x-4 peer-checked:bg-ink-950" />
      </span>
      <span className="min-w-0">
        <span className="block text-sm text-ink-100">{label}</span>
        {description && (
          <span className="mt-0.5 block text-xs leading-relaxed text-ink-500">{description}</span>
        )}
      </span>
    </label>
  )
}

export function ProgressBar({
  value,
  tone = 'accent',
  className = '',
  animated,
}: {
  value: number
  tone?: 'accent' | 'good' | 'bad' | 'muted'
  className?: string
  animated?: boolean
}) {
  const color = {
    accent: 'bg-accent-500',
    good: 'bg-signal-good',
    bad: 'bg-signal-bad',
    muted: 'bg-ink-600',
  }[tone]
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-ink-800 ${className}`}>
      <div
        className={`h-full origin-left rounded-full transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${color} ${animated ? 'shimmer' : ''}`}
        style={{ transform: `scaleX(${Math.max(0, Math.min(1, value))})` }}
      />
    </div>
  )
}

const STATUS_META: Record<JobStatus, { label: string; className: string; dot: string }> = {
  queued: { label: 'Na fila', className: 'text-ink-300', dot: 'bg-ink-500' },
  running: { label: 'Processando', className: 'text-accent-400', dot: 'bg-accent-400 animate-pulse' },
  done: { label: 'Concluído', className: 'text-signal-good', dot: 'bg-signal-good' },
  failed: { label: 'Falhou', className: 'text-signal-bad', dot: 'bg-signal-bad' },
  cancelled: { label: 'Cancelado', className: 'text-ink-400', dot: 'bg-ink-600' },
}

export function StatusBadge({ status, progress }: { status: JobStatus; progress?: number }) {
  const meta = STATUS_META[status] ?? STATUS_META.queued
  return (
    <span className={`chip ${meta.className}`}>
      <span className={`size-1.5 rounded-full ${meta.dot}`} />
      {status === 'running' && progress !== undefined
        ? `${Math.round(progress * 100)}%`
        : meta.label}
    </span>
  )
}

export function statusLabel(status: JobStatus): string {
  return STATUS_META[status]?.label ?? status
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className = '',
}: {
  icon: IconName
  title: React.ReactNode
  description?: React.ReactNode
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center rounded-2xl border border-dashed border-ink-750 px-6 py-10 text-center ${className}`}
    >
      <span className="grid size-11 place-items-center rounded-xl bg-ink-850 text-ink-400">
        <Icon name={icon} size={20} />
      </span>
      <p className="mt-4 text-sm font-semibold text-ink-200">{title}</p>
      {description && (
        <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-ink-500">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Loading({ label = 'Carregando…' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 pt-24 text-sm text-ink-400">
      <Spinner className="text-accent-500" />
      {label}
    </div>
  )
}

/** Inline callout for warnings and tips. */
export function Callout({
  tone = 'info',
  title,
  children,
  action,
}: {
  tone?: 'info' | 'warn' | 'bad' | 'good'
  title?: React.ReactNode
  children?: React.ReactNode
  action?: React.ReactNode
}) {
  const meta = {
    info: { icon: 'info' as const, color: 'text-ink-300', border: 'border-ink-750', bg: 'bg-ink-850' },
    warn: { icon: 'alert' as const, color: 'text-signal-warn', border: 'border-signal-warn/30', bg: 'bg-signal-warn/[0.06]' },
    bad: { icon: 'alert' as const, color: 'text-signal-bad', border: 'border-signal-bad/30', bg: 'bg-signal-bad/[0.06]' },
    good: { icon: 'check' as const, color: 'text-signal-good', border: 'border-signal-good/30', bg: 'bg-signal-good/[0.06]' },
  }[tone]
  return (
    <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${meta.border} ${meta.bg}`}>
      <Icon name={meta.icon} size={17} className={`mt-0.5 ${meta.color}`} />
      <div className="min-w-0 flex-1 text-sm leading-relaxed text-ink-300">
        {title && <p className="font-semibold text-ink-100">{title}</p>}
        {children && <div className={title ? 'mt-0.5' : ''}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

/** Numbered progress through a multi-step flow. */
export function Stepper({
  steps,
  current,
}: {
  steps: { label: string; hint?: string }[]
  current: number
}) {
  return (
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {steps.map((step, index) => {
        const state = index < current ? 'done' : index === current ? 'active' : 'todo'
        return (
          <li key={step.label} className="flex items-center gap-3">
            <span className="flex items-center gap-2.5">
              <span
                className={[
                  'numeric grid size-7 place-items-center rounded-full text-xs font-bold transition-colors',
                  state === 'done'
                    ? 'bg-accent-500/15 text-accent-400'
                    : state === 'active'
                      ? 'bg-accent-500 text-ink-950'
                      : 'bg-ink-800 text-ink-500',
                ].join(' ')}
              >
                {state === 'done' ? <Icon name="check" size={14} strokeWidth={3} /> : index + 1}
              </span>
              <span className="leading-tight">
                <span
                  className={`block text-sm font-semibold ${state === 'todo' ? 'text-ink-500' : 'text-ink-100'}`}
                >
                  {step.label}
                </span>
                {step.hint && <span className="block text-[11px] text-ink-500">{step.hint}</span>}
              </span>
            </span>
            {index < steps.length - 1 && (
              <span className="hidden h-px w-8 bg-ink-750 sm:block" aria-hidden />
            )}
          </li>
        )
      })}
    </ol>
  )
}
