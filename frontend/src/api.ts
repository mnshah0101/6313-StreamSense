/** Typed client for the StreamSense API (../backend). JSON is camelCase. */
import type { Alert, Analysis, AnalysisMeta, Feedback, FeedbackCreate, FeedbackSummary, Frame, Game, Job, ModelRun, Role, StatusRange, SystemStatus, Threshold, User } from './data/types'

/** Absolute (http://host:port) or same-origin path (e.g. /api behind the Vite dev proxy). */
export const API_BASE = String(import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')

/**
 * Auth is a session cookie (HttpOnly, set by POST /auth/login) that the browser sends on its own.
 * Every non-GET request to the API carries this header; the API rejects one without it (CSRF).
 */
const CSRF_HEADER = 'X-Requested-With'
const CSRF_VALUE = 'streamsense'

/** 401 codes that mean "no valid session" (not a wrong password). */
const SIGNED_OUT_CODES = new Set(['not_signed_in', 'session_expired', 'account_disabled'])
let onSignedOut: ((code: string) => void) | null = null
/** Called (once per failing request) when the API says the session is gone. */
export function setSignedOutHandler(fn: ((code: string) => void) | null) { onSignedOut = fn }
function checkSession(e: ApiError): ApiError {
  if (e.status === 401 && SIGNED_OUT_CODES.has(e.code)) onSignedOut?.(e.code)
  return e
}

/** An API failure. `status` 0 = the request never reached the server. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId?: string | null
  constructor(status: number, code: string, message: string, requestId?: string | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

/** Absolute URL for an API-relative media path (may 307 to S3; <img src> follows it). */
export function mediaUrl(path: string | null | undefined): string | undefined {
  if (!path) return undefined
  return /^https?:\/\//.test(path) ? path : `${API_BASE}${path}`
}

type Query = Record<string, string | number | boolean | null | undefined>

/** Turn a non-2xx response body into an ApiError using the API's error envelope. */
function envelopeError(status: number, text: string): ApiError {
  let env: { error?: { code?: string; message?: string; fields?: { loc?: unknown[]; msg?: string }[] }; requestId?: string } | undefined
  try { env = text ? JSON.parse(text) : undefined } catch { /* non-JSON body */ }
  let message = env?.error?.message ?? `Request failed (${status})`
  // Validation errors (422 invalid_request) list the offending fields.
  const fields = env?.error?.fields?.map((f) => (Array.isArray(f.loc) ? String(f.loc[f.loc.length - 1]) : '')).filter(Boolean)
  if (fields?.length) message = `${message}: check ${[...new Set(fields)].join(', ')}.`
  return new ApiError(status, env?.error?.code ?? 'http_error', message, env?.requestId)
}

function apiUrl(path: string, query: Query = {}): URL {
  // Resolves both an absolute VITE_API_URL and a same-origin path like /api.
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v))
  }
  return url
}

async function request<T>(method: string, path: string, opts: { query?: Query; json?: unknown } = {}): Promise<T> {
  const url = apiUrl(path, opts.query)
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers[CSRF_HEADER] = CSRF_VALUE
  let body: BodyInit | undefined
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.json)
  }
  let res: Response
  try {
    res = await fetch(url, { method, headers, body })
  } catch {
    throw new ApiError(0, 'network_error', `Cannot reach the StreamSense API at ${API_BASE}.`)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!res.ok) throw checkSession(envelopeError(res.status, text))
  try { return (text ? JSON.parse(text) : undefined) as T } catch {
    throw new ApiError(res.status, 'bad_response', 'The API returned a response that is not JSON.')
  }
}

export interface UploadProgress { loaded: number; total: number }

/**
 * POST /analyses (multipart): the footage plus its game metadata. Uses XMLHttpRequest because
 * fetch() reports no upload progress. Abort with `signal`; the promise then rejects with
 * ApiError code "aborted".
 */
function createAnalysis(file: File, meta: AnalysisMeta, onProgress?: (p: UploadProgress) => void, signal?: AbortSignal): Promise<Analysis> {
  const form = new FormData()
  const fields: [string, string | undefined][] = [
    ['home', meta.home], ['away', meta.away], ['sport', meta.sport], ['league', meta.league], ['venue', meta.venue],
    ['camera', meta.camera], ['date', meta.date], ['start_time', meta.startTime],
  ]
  for (const [k, v] of fields) if (v !== undefined && v.trim() !== '') form.append(k, v.trim())
  form.append('file', file, file.name)

  return new Promise<Analysis>((resolve, reject) => {
    if (signal?.aborted) { reject(new ApiError(0, 'aborted', 'Upload cancelled.')); return }
    const xhr = new XMLHttpRequest()
    xhr.open('POST', apiUrl('/analyses').toString())
    xhr.setRequestHeader(CSRF_HEADER, CSRF_VALUE)
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.upload.onprogress = (e) => onProgress?.({ loaded: e.loaded, total: e.lengthComputable ? e.total : file.size })
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText) as Analysis) } catch {
          reject(new ApiError(xhr.status, 'bad_response', 'The API returned a response that is not JSON.'))
        }
      } else reject(checkSession(envelopeError(xhr.status, xhr.responseText)))
    }
    xhr.onerror = () => reject(new ApiError(0, 'network_error', `Cannot reach the StreamSense API at ${API_BASE}.`))
    xhr.onabort = () => reject(new ApiError(0, 'aborted', 'Upload cancelled.'))
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(form)
  })
}

/** What the API supports for uploads (GET /model). */
export interface UploadCaps { directUpload: boolean; maxUploadMb: number; maxVideoSec: number }

interface UploadPlan { uploadId: string; partSize: number; parts: { partNumber: number; url: string }[] }

/** PUT one part straight to S3 (presigned URL; no API headers, they would break the signature/CORS). */
function putPart(url: string, body: Blob, onLoaded: (n: number) => void, signal?: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    xhr.upload.onprogress = (e) => onLoaded(e.loaded)
    xhr.onload = () => {
      const etag = xhr.getResponseHeader('ETag')
      if (xhr.status >= 200 && xhr.status < 300 && etag) resolve(etag)
      else if (xhr.status >= 200 && xhr.status < 300) {
        reject(new ApiError(0, 'cors', 'S3 hid the ETag header: the bucket CORS rule must expose ETag.'))
      } else reject(new ApiError(xhr.status, 's3_error', `S3 rejected a part (${xhr.status}).`))
    }
    xhr.onerror = () => reject(new ApiError(0, 'network_error', 'Network error while uploading to S3 (check the bucket CORS rule).'))
    xhr.onabort = () => reject(new ApiError(0, 'aborted', 'Upload cancelled.'))
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(body)
  })
}

/**
 * Large-file path: the browser uploads straight to S3 in parts (4 in flight, 3 tries each),
 * so the bytes skip the API host and any tunnel; then the API assembles them and queues the job.
 */
async function createAnalysisDirect(file: File, meta: AnalysisMeta, onProgress?: (p: UploadProgress) => void, signal?: AbortSignal): Promise<Analysis> {
  const plan = await request<UploadPlan>('POST', '/uploads', { json: { filename: file.name, contentType: file.type, size: file.size } })
  const loaded = new Map<number, number>()
  const report = () => onProgress?.({ loaded: [...loaded.values()].reduce((a, b) => a + b, 0), total: file.size })
  const etags = new Map<number, string>()
  const queue = [...plan.parts]
  const worker = async () => {
    for (let p = queue.shift(); p; p = queue.shift()) {
      const start = (p.partNumber - 1) * plan.partSize
      const blob = file.slice(start, Math.min(file.size, start + plan.partSize))
      for (let attempt = 1; ; attempt++) {
        try {
          const n = p.partNumber
          etags.set(n, await putPart(p.url, blob, (b) => { loaded.set(n, b); report() }, signal))
          break
        } catch (e) {
          if (signal?.aborted || attempt >= 3 || (e instanceof ApiError && e.code === 'cors')) throw e
          await new Promise((r) => setTimeout(r, 1000 * attempt))
        }
      }
    }
  }
  try {
    await Promise.all(Array.from({ length: Math.min(4, plan.parts.length) }, worker))
  } catch (e) {
    void request('POST', `/uploads/${plan.uploadId}/abort`).catch(() => undefined)
    throw e
  }
  const parts = [...etags].map(([partNumber, etag]) => ({ partNumber, etag }))
  const clean = Object.fromEntries(Object.entries(meta).filter(([, v]) => v !== undefined && String(v).trim() !== ''))
  return request<Analysis>('POST', `/uploads/${plan.uploadId}/complete`, { json: { parts, ...clean } })
}

let caps: Promise<UploadCaps> | null = null
/** Cached GET /model upload capabilities (defaults if the API is older). */
export function uploadCaps(): Promise<UploadCaps> {
  caps ??= request<Partial<UploadCaps>>('GET', '/model')
    .then((m) => ({ directUpload: !!m.directUpload, maxUploadMb: m.maxUploadMb || 10240, maxVideoSec: m.maxVideoSec || 36000 }))
    .catch(() => { caps = null; return { directUpload: false, maxUploadMb: 10240, maxVideoSec: 36000 } })
  return caps
}

/** Upload + analyze: straight to S3 when the API supports it, else through POST /analyses. */
async function startAnalysis(file: File, meta: AnalysisMeta, onProgress?: (p: UploadProgress) => void, signal?: AbortSignal): Promise<Analysis> {
  return (await uploadCaps()).directUpload ? createAnalysisDirect(file, meta, onProgress, signal) : createAnalysis(file, meta, onProgress, signal)
}

export interface GameFilters { q?: string; sport?: string; status?: string; camera?: string; defect?: string }

export const api = {
  // Session
  login: (email: string, password: string) => request<User>('POST', '/auth/login', { json: { email, password } }),
  logout: () => request<void>('POST', '/auth/logout'),
  me: () => request<User>('GET', '/auth/me'),
  /** Revokes every session of this user, including this one: sign in again after. */
  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>('POST', '/auth/password', { json: { currentPassword, newPassword } }),

  // Admin: users
  listUsers: () => request<User[]>('GET', '/users'),
  createUser: (u: { email: string; name: string; role: Role; password: string }) => request<User>('POST', '/users', { json: u }),
  updateUser: (id: number, patch: { name?: string; role?: Role; active?: boolean }) => request<User>('PATCH', `/users/${id}`, { json: patch }),
  resetPassword: (id: number, password: string) => request<void>('POST', `/users/${id}/password`, { json: { password } }),

  // Games catalog + Match Analysis
  listGames: (f: GameFilters = {}) => request<Game[]>('GET', '/games', { query: { ...f } }),
  getGame: (id: string) => request<Game>('GET', `/games/${encodeURIComponent(id)}`),
  gameFrames: (id: string, q: { start?: number; end?: number; flagged?: boolean } = {}) =>
    request<Frame[]>('GET', `/games/${encodeURIComponent(id)}/frames`, { query: q }),

  // New analysis (upload + metadata) and jobs
  createAnalysis: startAnalysis,
  /** Re-run the analysis of a game's stored footage (returns the active job on a double click). */
  rerunAnalysis: (gameId: string) => request<Job>('POST', '/jobs/match', { json: { gameId } }),
  listJobs: (q: { gameId?: string; status?: string; limit?: number } = {}) =>
    request<Job[]>('GET', '/jobs', { query: { game_id: q.gameId, status: q.status, limit: q.limit } }),
  getJob: (id: string) => request<Job>('GET', `/jobs/${encodeURIComponent(id)}`),

  // Alerts
  listAlerts: (q: { status?: string; gameId?: string } = {}) =>
    request<Alert[]>('GET', '/alerts', { query: { status: q.status, game_id: q.gameId } }),
  reviewAlert: (id: string, decision: 'confirmed' | 'dismissed', expectedVersion: number) =>
    request<Alert>('POST', `/alerts/${encodeURIComponent(id)}/review`, { json: { decision, expectedVersion } }),

  // Feedback
  listFeedback: (gameId?: string) => request<Feedback[]>('GET', '/feedback', { query: { game_id: gameId } }),
  addFeedback: (f: FeedbackCreate) => request<Feedback>('POST', '/feedback', { json: f }),
  deleteFeedback: (id: string) => request<void>('DELETE', `/feedback/${encodeURIComponent(id)}`),
  feedbackSummary: () => request<FeedbackSummary>('GET', '/feedback/summary'),
  feedbackExportUrl: `${API_BASE}/feedback/export.csv`,
  queueFineTune: () => request<{ id: number; labels: number; status: string }>('POST', '/feedback/fine-tune'),

  // Model Performance
  listRuns: () => request<ModelRun[]>('GET', '/runs'),
  currentThreshold: () => request<Threshold>('GET', '/thresholds/current'),
  publishThreshold: (alertThreshold: number) => request<Threshold>('POST', '/thresholds', { json: { alertThreshold } }),

  // System status (any signed-in user)
  status: (range: StatusRange) => request<SystemStatus>('GET', '/status', { query: { range } }),
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
