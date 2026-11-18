/**
 * Typed client for the AutoClip API.
 *
 * Same-origin throughout: the server hands out the built bundle, so there is no
 * base URL to configure and no CORS to negotiate.
 */

export interface Source {
  id: string
  type: string
  title: string
  url: string | null
  filename: string | null
  channel: string | null
  duration_s: number
  width: number | null
  height: number | null
  fps: number | null
  has_audio: boolean
  has_video: boolean
  created_at: string
}

export type JobStatus = 'queued' | 'running' | 'failed' | 'done' | 'cancelled'

export interface JobLog {
  id: string
  timestamp: string
  level: string
  logger: string
  message: string
}

export interface Job {
  id: string
  source_id: string
  status: JobStatus
  current_stage: string
  progress: number
  error: string | null
  provider: string
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  source: Source | null
}

export interface ExportRecord {
  id: string
  clip_id: string
  ratio: string
  style: string
  size_bytes: number
  created_at: string
  download_url: string
}

export type ClipStatus = 'candidate' | 'kept' | 'discarded' | 'exported'

export interface Clip {
  id: string
  job_id: string
  rank: number
  start_s: number
  end_s: number
  duration_s: number
  start_word: number
  end_word: number
  title: string
  hook: string
  score: number
  reason: string
  status: ClipStatus
  user_trimmed: boolean
  caption_style: string
  ratio: string
  exports: ExportRecord[]
}

export interface Word {
  text: string
  start: number
  end: number
  speaker: string | null
}

export interface CropKeyframe {
  t: number
  x: number
  y: number
}

export interface CropSegment {
  start_s: number
  end_s: number
  width: number
  height: number
  keyframes: CropKeyframe[]
  strategy: 'track' | 'wide' | 'general'
  zoom: number
  fit: boolean
}

/** Mirrors autoclip.pipeline.reframe.croppath.CropPath. */
export interface CropPath {
  source_width: number
  source_height: number
  segments: CropSegment[]
}

export interface CaptionStyle {
  key: string
  label: string
  description: string
  preview: {
    font: string
    primary: string
    accent: string | null
    outline: string
    outlineWidth: number
    allCaps: boolean
    sizeRatio: number
    marginRatio: number
    boxed: boolean
    animation: string
    maxWords: number
  }
}

export interface ProviderStatus {
  name: string
  available: boolean
  detail: string
  models: string[]
  requires_key: boolean
  has_key: boolean
}

export interface Settings {
  active_provider: string
  providers: Record<string, { model: string; base_url: string | null }>
  whisper: { model: string; compute_type: string; language: string; diarization: boolean }
  clips: { min_duration_s: number; max_duration_s: number; max_clips: number }
  ingest: {
    ytdlp_format: string
    cookies_from_browser: string
    prefer_youtube_captions: boolean
  }
  export: {
    ratio: string
    caption_style: string
    loudness_lufs: number
    prefer_hardware_encoder: boolean
    crf: number
    write_srt: boolean
  }
  insecure_secret_storage: boolean
  keys_present: Record<string, boolean>
}

export interface SystemStatus {
  ready: boolean
  python_version: string
  platform: string
  ffmpeg_version: string | null
  has_libass: boolean
  nvenc_works: boolean
  accel: string
  gpu_name: string | null
  compute_type: string
  diarization_available: boolean
}

export interface JobSettingsOverrides {
  provider?: string
  whisper_model?: string
  language?: string
  diarization?: boolean
  min_duration_s?: number
  max_duration_s?: number
  max_clips?: number
  caption_style?: string
  ratio?: string
}

export interface CreationBrief {
  topic: string
  niche: 'biblical' | 'technology' | 'general'
  duration_s: number
  language: 'pt-BR' | 'en' | 'es'
  audience: string
  visual_style: 'illustrated' | 'motion_graphics'
  reference_notes: string
  instructions: string
}

export interface StoryboardScene {
  narration: string
  visual_description: string
  on_screen_text: string
  image_id?: string | null
  media_type?: 'image' | 'video'
}

export interface Storyboard {
  title: string
  description: string
  scenes: StoryboardScene[]
  references: string[]
  review_notes: string[]
  narration_word_count: number
  estimated_duration_s: number
}

export interface Creation {
  id: string
  brief: CreationBrief
  storyboard: Storyboard
  provider: string
  model: string
  revision: number
  created_at: string
  updated_at: string
}

export interface RenderOptions {
  voice: string | null
  rate_percent: number
  resolution: '720p' | '1080p'
  caption_style: 'bold_pop' | 'karaoke_fill' | 'clean_lower' | 'boxed'
}

export interface CreationRender {
  id: string
  creation_id: string
  revision: number
  options: RenderOptions
  status: JobStatus
  stage: string
  progress: number
  error: string | null
  duration_s: number
  created_at: string
  updated_at: string
}

/** An API error carrying the server's message and its actionable hint. */
export class ApiError extends Error {
  hint: string
  status: number

  constructor(message: string, status: number, hint = '') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.hint = hint
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    let hint = ''
    try {
      const body = await response.json()
      const detail = body.detail
      if (typeof detail === 'string') {
        message = detail
      } else if (detail && typeof detail === 'object') {
        // The ingest endpoints return {message, hint} so the UI can show the
        // fix alongside the failure.
        message = detail.message ?? message
        hint = detail.hint ?? ''
      }
    } catch {
      /* Response had no JSON body; the status line is the best we have. */
    }
    throw new ApiError(message, response.status, hint)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),
  system: () => request<SystemStatus>('/api/system'),
  fetchModels: () => request<void>('/api/system/models', { method: 'POST' }),

  listSources: () => request<Source[]>('/api/sources'),

  ingestYouTube: (url: string, cookiesFromBrowser?: string) =>
    request<Source>('/api/sources/youtube', {
      method: 'POST',
      body: JSON.stringify({ url, cookies_from_browser: cookiesFromBrowser || null }),
    }),

  uploadSource: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Source>('/api/sources/upload', { method: 'POST', body: form })
  },

  listJobs: (limit = 25) => request<Job[]>(`/api/jobs?limit=${limit}`),

  listCreations: () => request<Creation[]>('/api/creations'),
  importCreation: (brief: CreationBrief, storyboard: Storyboard) =>
    request<Creation>('/api/creations/import', {
      method: 'POST', body: JSON.stringify({brief, storyboard}),
    }),
  getCreation: (id: string) => request<Creation>(`/api/creations/${id}`),
  generateCreation: (brief: CreationBrief, provider?: string) =>
    request<Creation>('/api/creations', {
      method: 'POST',
      body: JSON.stringify({ brief, provider }),
    }),
  saveCreation: (id: string, storyboard: Storyboard, revision: number) =>
    request<Creation>(`/api/creations/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ storyboard, revision }),
    }),
  creationDownloadUrl: (id: string) => `/api/creations/${id}/download`,
  creationVoices: (id: string) =>
    request<{id: string; label: string; default: boolean}[]>(`/api/creations/${id}/voices`),
  uploadCreationImage: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{image_id: string; media_type: 'image' | 'video'}>(`/api/creations/${id}/images`, {method: 'POST', body: form})
  },
  creationImageUrl: (id: string, imageId: string) => `/api/creations/${id}/images/${imageId}`,
  createRender: (id: string, revision: number, options: RenderOptions) =>
    request<CreationRender>(`/api/creations/${id}/renders`, {
      method: 'POST', body: JSON.stringify({revision, options}),
    }),
  listCreationRenders: (id: string) => request<CreationRender[]>(`/api/creations/${id}/renders`),
  cancelCreationRender: (id: string, renderId: string) =>
    request<CreationRender>(`/api/creations/${id}/renders/${renderId}/cancel`, {method: 'POST'}),
  retryCreationRender: (id: string, renderId: string) =>
    request<CreationRender>(`/api/creations/${id}/renders/${renderId}/retry`, {method: 'POST'}),
  creationRenderMediaUrl: (id: string, renderId: string, download = false) =>
    `/api/creations/${id}/renders/${renderId}/media${download ? '?download=true' : ''}`,
  creationRenderSubtitlesUrl: (id: string, renderId: string) =>
    `/api/creations/${id}/renders/${renderId}/subtitles`,

  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  getJobLogs: (id: string) => request<JobLog[]>(`/api/jobs/${id}/logs`),

  createJob: (sourceId: string, settings: JobSettingsOverrides = {}) =>
    request<Job>('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ source_id: sourceId, settings }),
    }),

  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),

  listClips: (jobId: string) => request<Clip[]>(`/api/jobs/${jobId}/clips`),
  getClip: (clipId: string) => request<Clip>(`/api/clips/${clipId}`),

  getCropPath: (clipId: string) => request<CropPath>(`/api/clips/${clipId}/crop-path`),
  getClipWords: (clipId: string) => request<Word[]>(`/api/clips/${clipId}/words`),

  patchClip: (
    clipId: string,
    patch: { start_s?: number; end_s?: number; title?: string; status?: ClipStatus },
  ) => request<Clip>(`/api/clips/${clipId}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  patchCaptions: (
    clipId: string,
    patch: { words?: Word[]; caption_style?: string; ratio?: string },
  ) =>
    request<Clip>(`/api/clips/${clipId}/captions`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  exportClip: (clipId: string, ratio: string, style: string, writeSrt = false) =>
    request<ExportRecord>(`/api/clips/${clipId}/export`, {
      method: 'POST',
      body: JSON.stringify({ ratio, style, write_srt: writeSrt }),
    }),

  captionStyles: () => request<CaptionStyle[]>('/api/caption-styles'),
  providerStatus: () => request<ProviderStatus[]>('/api/providers/status'),

  getSettings: () => request<Settings>('/api/settings'),
  putSettings: (patch: Partial<Settings>) =>
    request<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(patch) }),

  putSecret: (key: string, value: string) =>
    request<void>('/api/settings/secrets', {
      method: 'PUT',
      body: JSON.stringify({ key, value }),
    }),

  deleteSecret: (key: string) =>
    request<void>(`/api/settings/secrets/${key}`, { method: 'DELETE' }),

  mediaUrl: (jobId: string) => `/api/jobs/${jobId}/media`,
}

/** Format seconds as m:ss, or h:mm:ss past an hour. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const s = total % 60
  const m = Math.floor(total / 60) % 60
  const h = Math.floor(total / 3600)
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

/** Format seconds as timecode with centiseconds, for trim handles. */
export function formatTimecode(seconds: number): string {
  const total = Math.max(0, seconds)
  const cs = Math.floor((total % 1) * 100)
  const s = Math.floor(total) % 60
  const m = Math.floor(total / 60)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(m)}:${pad(s)}.${pad(cs)}`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`
}

/** "há 3 min", "ontem", or a date — enough to scan a list by recency. */
export function formatRelative(iso: string): string {
  const date = new Date(iso)
  const diff = (Date.now() - date.getTime()) / 1000
  if (Number.isNaN(diff)) return ''
  if (diff < 60) return 'agora'
  if (diff < 3600) return `há ${Math.floor(diff / 60)} min`
  if (diff < 86400) return `há ${Math.floor(diff / 3600)} h`
  if (diff < 172800) return 'ontem'
  return date.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })
}
