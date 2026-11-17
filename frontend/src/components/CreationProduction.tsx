import { useEffect, useState } from 'react'

import { api, formatDuration, type Creation, type CreationRender, type RenderOptions } from '../api'
import { ErrorNote } from './ErrorNote'
import { Icon, Spinner } from './Icon'
import { Field, ProgressBar, Segmented } from './ui'

const CAPTION_STYLES: { value: RenderOptions['caption_style']; label: string }[] = [
  { value: 'bold_pop', label: 'Bold Pop — palavras grandes que saltam' },
  { value: 'karaoke_fill', label: 'Karaokê — a palavra falada acende' },
  { value: 'clean_lower', label: 'Discreta — texto limpo embaixo' },
  { value: 'boxed', label: 'Com fundo — caixa escura atrás do texto' },
]

const RATES = [-20, -10, 0, 10, 20, 30]

export function CreationProduction({ creation, disabled }: { creation: Creation; disabled: boolean }) {
  const [options, setOptions] = useState<RenderOptions>({
    voice: null,
    rate_percent: 0,
    resolution: '720p',
    caption_style: 'bold_pop',
  })
  const [voices, setVoices] = useState<{ id: string; label: string }[]>([])
  const [renders, setRenders] = useState<CreationRender[]>([])
  const [error, setError] = useState<Error | null>(null)
  const [pollError, setPollError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    api
      .creationVoices(creation.id)
      .then((result) => {
        if (active) setVoices(result)
      })
      .catch((err: Error) => {
        if (active) setError(err)
      })
    return () => {
      active = false
    }
  }, [creation.id])

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    async function poll() {
      try {
        const result = await api.listCreationRenders(creation.id)
        if (!active) return
        setRenders(result)
        setPollError(null)
        if (result.some((item) => item.status === 'queued' || item.status === 'running')) {
          timer = setTimeout(() => void poll(), 1500)
        }
      } catch (err) {
        if (active) {
          setPollError(err as Error)
          timer = setTimeout(() => void poll(), 5000)
        }
      }
    }
    void poll()
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [creation.id, refresh])

  async function act(action: () => Promise<CreationRender>) {
    setBusy(true)
    setError(null)
    try {
      const record = await action()
      setRenders((current) => [record, ...current.filter((item) => item.id !== record.id)])
      setRefresh((value) => value + 1)
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const pending = renders.find((item) => item.status === 'queued' || item.status === 'running')
  const latest = renders[0]
  const completed = renders.find((item) => item.status === 'done')
  const locked = busy || !!pending

  return (
    <section className="card overflow-hidden" aria-label="Produção do vídeo">
      <div className="flex items-center gap-3 border-b border-ink-800 p-5">
        <span className="grid size-10 place-items-center rounded-xl bg-accent-500 text-ink-950">
          <Icon name="film" size={19} />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-ink-100">Produzir vídeo</h2>
          <p className="text-xs text-ink-500">Narração, movimento de câmera e legendas · 9:16</p>
        </div>
      </div>

      {/* Result */}
      {completed && (
        <div className="border-b border-ink-800 bg-ink-900/60 p-5">
          <video
            key={completed.id}
            controls
            playsInline
            preload="metadata"
            poster={`/api/creations/${creation.id}/renders/${completed.id}/poster`}
            src={api.creationRenderMediaUrl(creation.id, completed.id)}
            className="mx-auto aspect-[9/16] w-full max-w-[15rem] rounded-xl bg-black shadow-[0_24px_48px_-24px_rgb(0_0_0/0.9)]"
          />
          <p className="numeric mt-3 text-center text-xs text-ink-400">
            Versão {completed.revision} · {formatDuration(completed.duration_s)} · {completed.options.resolution}
          </p>
          {completed.revision !== creation.revision && (
            <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-xs text-signal-warn">
              <Icon name="alert" size={13} />
              Feito com uma versão anterior do roteiro.
            </p>
          )}
          <div className="mt-4 grid grid-cols-2 gap-2">
            <a className="btn btn-primary" href={api.creationRenderMediaUrl(creation.id, completed.id, true)}>
              <Icon name="download" size={15} /> MP4
            </a>
            <a className="btn btn-ghost" href={api.creationRenderSubtitlesUrl(creation.id, completed.id)}>
              <Icon name="captions" size={15} /> Legenda SRT
            </a>
          </div>
        </div>
      )}

      <div className="space-y-4 p-5">
        <Field label="Voz" htmlFor="production-voice">
          <select
            className="input"
            id="production-voice"
            value={options.voice ?? ''}
            disabled={locked}
            onChange={(event) => setOptions({ ...options, voice: event.target.value || null })}
          >
            <option value="">Voz padrão do idioma</option>
            {voices.map((voice) => (
              <option key={voice.id} value={voice.id}>{voice.label}</option>
            ))}
          </select>
        </Field>

        <Field label="Velocidade da fala" htmlFor="production-rate">
          <select
            className="input"
            id="production-rate"
            value={options.rate_percent}
            disabled={locked}
            onChange={(event) => setOptions({ ...options, rate_percent: Number(event.target.value) })}
          >
            {RATES.map((rate) => (
              <option key={rate} value={rate}>
                {rate === 0 ? 'Normal' : `${rate > 0 ? '+' : ''}${rate}% ${rate > 0 ? '(mais rápida)' : '(mais lenta)'}`}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Estilo da legenda" htmlFor="production-captions">
          <select
            className="input"
            id="production-captions"
            value={options.caption_style}
            disabled={locked}
            onChange={(event) =>
              setOptions({ ...options, caption_style: event.target.value as RenderOptions['caption_style'] })
            }
          >
            {CAPTION_STYLES.map((style) => (
              <option key={style.value} value={style.value}>{style.label}</option>
            ))}
          </select>
        </Field>

        <Field label="Resolução">
          <Segmented<RenderOptions['resolution']>
            ariaLabel="Resolução"
            className="w-full"
            value={options.resolution}
            disabled={locked}
            onChange={(resolution) => setOptions({ ...options, resolution })}
            options={[
              { value: '720p', label: '720p', title: '720 × 1280 — mais rápido' },
              { value: '1080p', label: '1080p', title: '1080 × 1920 — melhor qualidade' },
            ]}
          />
        </Field>

        <button
          type="button"
          className="btn btn-primary btn-lg w-full"
          disabled={disabled || locked}
          onClick={() => void act(() => api.createRender(creation.id, creation.revision, options))}
        >
          {busy ? (
            <><Spinner /> Aguarde…</>
          ) : pending ? (
            <><Spinner /> Produzindo…</>
          ) : (
            <><Icon name="play" size={15} strokeWidth={0} className="fill-current" /> {completed ? 'Gerar nova versão' : 'Gerar vídeo MP4'}</>
          )}
        </button>

        {disabled && !pending && (
          <p className="flex items-start gap-1.5 text-xs leading-relaxed text-signal-warn">
            <Icon name="info" size={13} className="mt-0.5" />
            Salve as alterações do roteiro (e aguarde os envios de imagem) antes de gerar o vídeo.
          </p>
        )}

        {pending && (
          <div role="status" className="fade-in rounded-xl border border-accent-600/40 bg-accent-500/[0.05] p-4">
            <div className="flex items-center justify-between gap-4 text-sm">
              <span className="truncate font-semibold text-ink-100">{pending.stage || 'Na fila'}</span>
              <span className="numeric font-semibold text-accent-400">{Math.round(pending.progress * 100)}%</span>
            </div>
            <ProgressBar value={pending.progress} animated className="mt-3" />
            <p className="mt-3 text-xs leading-relaxed text-ink-500">
              Roteiro versão {pending.revision}. Pode sair desta página — a produção continua e
              você acompanha ao voltar.
            </p>
            <button
              type="button"
              className="btn btn-danger btn-sm -ml-2 mt-2"
              disabled={busy}
              onClick={() => void act(() => api.cancelCreationRender(creation.id, pending.id))}
            >
              <Icon name="x" size={13} /> Cancelar produção
            </button>
          </div>
        )}

        {!pending && latest && (latest.status === 'failed' || latest.status === 'cancelled') && (
          <div className="rounded-xl border border-signal-bad/30 bg-signal-bad/[0.05] p-4">
            <p className="flex items-start gap-2 whitespace-pre-line text-sm text-signal-bad [overflow-wrap:anywhere]">
              <Icon name="alert" size={15} className="mt-0.5" />
              {latest.error || 'Produção cancelada.'}
            </p>
            <button
              type="button"
              className="btn btn-ghost btn-sm mt-3"
              disabled={locked}
              onClick={() => void act(() => api.retryCreationRender(creation.id, latest.id))}
            >
              <Icon name="refresh" size={13} /> Retomar produção
            </button>
            <p className="mt-2 text-xs text-ink-500">
              Retoma a versão {latest.revision} com as opções originais e reaproveita as cenas concluídas.
            </p>
          </div>
        )}

        {(error || pollError) && (
          <ErrorNote
            error={(error || pollError)!}
            onDismiss={() => {
              setError(null)
              setPollError(null)
            }}
          />
        )}

        {!completed && !pending && (
          <div className="flex items-center gap-3 rounded-xl border border-dashed border-ink-750 p-4 text-xs leading-relaxed text-ink-500">
            <span className="grid aspect-[9/16] w-8 shrink-0 place-items-center rounded-md bg-ink-800 text-ink-500">
              <Icon name="play" size={11} strokeWidth={0} className="fill-current" />
            </span>
            O vídeo pronto aparece aqui, com áudio e legendas.
          </div>
        )}

        <p className="text-[11px] leading-relaxed text-ink-600">
          A narração usa o serviço online da Microsoft (Edge TTS): as falas são enviadas para
          gerar o áudio. A montagem do vídeo acontece neste computador.
        </p>
      </div>
    </section>
  )
}
