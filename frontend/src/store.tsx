import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Alert, Analysis, Feedback, FeedbackCreate, FeedbackSummary, Game, Job, Threshold } from './data/types'
import { jobActive } from './data/types'
import { api, errorMessage } from './api'

/**
 * App state, backed by the StreamSense API. The server is the source of truth: nothing here is
 * persisted locally. Alerts are polled every 5 s, the catalog every 15 s, and active jobs every
 * 1.5 s until they finish.
 */
interface Store {
  games: Game[]
  gamesById: Record<string, Game>
  gamesLoaded: boolean
  apiError: string | null
  refreshGames: () => Promise<void>
  upsertGame: (g: Game) => void

  alerts: Alert[]
  refreshAlerts: () => Promise<void>
  /** Resolves with the reviewed alert; rejects with ApiError (409 = stale / already reviewed) after refetching. */
  reviewAlert: (alert: Alert, decision: 'confirmed' | 'dismissed') => Promise<Alert>

  feedback: Feedback[]
  feedbackSummary: FeedbackSummary | null
  refreshFeedback: () => Promise<void>
  addFeedback: (f: FeedbackCreate) => Promise<void>
  removeFeedback: (id: string) => Promise<void>

  jobs: Job[]
  refreshJobs: () => Promise<void>
  /** POST /jobs/match: re-run the analysis of a game's stored footage. */
  rerunAnalysis: (gameId: string) => Promise<Job>
  /** Record a just-created analysis (POST /analyses) so its game shows and its job is polled. */
  addAnalysis: (a: Analysis) => void
  /** Add/replace a job fetched elsewhere so it is polled while active. */
  trackJob: (job: Job) => void

  /** Slider preview value (also drives timeline brightness). */
  threshold: number
  /** Currently published severity cutoff. */
  savedThreshold: number
  thresholdVersion: Threshold | null
  setThreshold: (n: number) => void
  saveThreshold: () => Promise<Threshold>

  sidebarOpen: boolean
  unseenAlerts: number
  setSidebarOpen: (open: boolean) => void
  toggleSidebar: () => void
}

const Ctx = createContext<Store | null>(null)

const ALERT_POLL_MS = 5000
const CATALOG_POLL_MS = 15000
const JOB_POLL_MS = 1500

/** setInterval that always calls the latest callback and skips ticks while the tab is hidden. */
export function usePoll(fn: () => unknown, ms: number, enabled = true) {
  const ref = useRef(fn)
  useEffect(() => { ref.current = fn })
  useEffect(() => {
    if (!enabled) return
    const t = window.setInterval(() => { if (!document.hidden) ref.current() }, ms)
    return () => window.clearInterval(t)
  }, [ms, enabled])
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [games, setGames] = useState<Game[]>([])
  const [gamesLoaded, setGamesLoaded] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [feedback, setFeedback] = useState<Feedback[]>([])
  const [feedbackSummary, setFeedbackSummary] = useState<FeedbackSummary | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [thresholdVersion, setThresholdVersion] = useState<Threshold | null>(null)
  const [threshold, setThreshold] = useState(2)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  // Alert ids the reviewer has already been shown; anything else open counts as unseen.
  const [seen, setSeen] = useState<Set<string> | null>(null)

  const note = useCallback((e: unknown) => setApiError(errorMessage(e)), [])

  const refreshGames = useCallback(async () => {
    try {
      setGames(await api.listGames())
      setGamesLoaded(true)
      setApiError(null)
    } catch (e) { note(e) }
  }, [note])
  const upsertGame = useCallback((g: Game) => {
    setGames((prev) => (prev.some((x) => x.id === g.id) ? prev.map((x) => (x.id === g.id ? g : x)) : [...prev, g]))
  }, [])

  const refreshAlerts = useCallback(async () => {
    try {
      const list = await api.listAlerts()
      setAlerts(list)
      // First load: the existing queue is not "new".
      setSeen((s) => s ?? new Set(list.map((a) => a.id)))
    } catch (e) { note(e) }
  }, [note])

  const refreshFeedback = useCallback(async () => {
    try {
      const [list, summary] = await Promise.all([api.listFeedback(), api.feedbackSummary()])
      setFeedback(list)
      setFeedbackSummary(summary)
    } catch (e) { note(e) }
  }, [note])

  const refreshJobs = useCallback(async () => {
    try { setJobs(await api.listJobs({ limit: 50 })) } catch (e) { note(e) }
  }, [note])

  useEffect(() => {
    void refreshGames()
    void refreshAlerts()
    void refreshFeedback()
    void refreshJobs()
    api.currentThreshold().then((t) => { setThresholdVersion(t); setThreshold(t.alertThreshold) }).catch(note)
  }, [refreshGames, refreshAlerts, refreshFeedback, refreshJobs, note])

  usePoll(refreshAlerts, ALERT_POLL_MS)
  usePoll(refreshGames, CATALOG_POLL_MS)

  // Active jobs: poll each one; when one finishes, refresh what it changed.
  const activeIds = jobs.filter(jobActive).map((j) => j.id).join(',')
  usePoll(async () => {
    const ids = activeIds.split(',').filter(Boolean)
    const updated = await Promise.all(ids.map((id) => api.getJob(id).catch(() => null)))
    const fresh = updated.filter((j): j is Job => j !== null)
    if (!fresh.length) return
    setJobs((prev) => prev.map((j) => fresh.find((f) => f.id === j.id) ?? j))
    if (fresh.some((j) => !jobActive(j))) {
      void refreshGames()
      void refreshAlerts()
    }
  }, JOB_POLL_MS, activeIds !== '')

  const reviewAlert = useCallback(async (alert: Alert, decision: 'confirmed' | 'dismissed') => {
    try {
      const updated = await api.reviewAlert(alert.id, decision, alert.version)
      setAlerts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
      return updated
    } catch (e) {
      void refreshAlerts() // pick up the other reviewer's decision / new version
      throw e
    }
  }, [refreshAlerts])

  const addFeedback = useCallback(async (f: FeedbackCreate) => {
    const created = await api.addFeedback(f)
    setFeedback((prev) => [created, ...prev])
    api.feedbackSummary().then(setFeedbackSummary).catch(note)
  }, [note])
  const removeFeedback = useCallback(async (id: string) => {
    await api.deleteFeedback(id)
    setFeedback((prev) => prev.filter((f) => f.id !== id))
    api.feedbackSummary().then(setFeedbackSummary).catch(note)
  }, [note])

  const addJob = useCallback((job: Job) => {
    setJobs((prev) => [job, ...prev.filter((j) => j.id !== job.id)])
  }, [])
  const rerunAnalysis = useCallback(async (gameId: string) => {
    const job = await api.rerunAnalysis(gameId)
    addJob(job)
    api.getGame(gameId).then(upsertGame).catch(note)
    return job
  }, [addJob, upsertGame, note])
  const addAnalysis = useCallback((a: Analysis) => {
    upsertGame(a.game)
    addJob(a.job)
  }, [upsertGame, addJob])

  const savedThreshold = thresholdVersion?.alertThreshold ?? 2
  const saveThreshold = useCallback(async () => {
    const t = await api.publishThreshold(threshold)
    setThresholdVersion(t)
    return t
  }, [threshold])

  const openIds = alerts.filter((a) => a.status === 'open').map((a) => a.id)
  const unseenAlerts = sidebarOpen || !seen ? 0 : openIds.filter((id) => !seen.has(id)).length
  // Opening the sidebar marks everything as seen.
  const openKey = openIds.join(',')
  useEffect(() => {
    if (sidebarOpen) setSeen((s) => new Set([...(s ?? []), ...openKey.split(',').filter(Boolean)]))
  }, [sidebarOpen, openKey])

  const gamesById = useMemo(() => Object.fromEntries(games.map((g) => [g.id, g])), [games])

  const value = useMemo<Store>(
    () => ({
      games, gamesById, gamesLoaded, apiError, refreshGames, upsertGame,
      alerts, refreshAlerts, reviewAlert,
      feedback, feedbackSummary, refreshFeedback, addFeedback, removeFeedback,
      jobs, refreshJobs, rerunAnalysis, addAnalysis, trackJob: addJob,
      threshold, savedThreshold, thresholdVersion, setThreshold, saveThreshold,
      sidebarOpen, unseenAlerts, setSidebarOpen, toggleSidebar: () => setSidebarOpen((o) => !o),
    }),
    [games, gamesById, gamesLoaded, apiError, refreshGames, upsertGame, alerts, refreshAlerts, reviewAlert,
      feedback, feedbackSummary, refreshFeedback, addFeedback, removeFeedback, jobs, refreshJobs, rerunAnalysis,
      addAnalysis, addJob, threshold, savedThreshold, thresholdVersion, saveThreshold, sidebarOpen, unseenAlerts],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useStore(): Store {
  const s = useContext(Ctx)
  if (!s) throw new Error('useStore outside provider')
  return s
}
