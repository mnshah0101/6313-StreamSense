import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { DEFECT_TYPES, type ModelRun, type Threshold } from '../data/types'
import { useStore } from '../store'
import { useAuth } from '../auth'
import { api, errorMessage } from '../api'
import { Eyebrow, Kpi, Pill, btnGhost, btnPrimary, cardCls, inputCls } from '../components/ui'

/** Tradeoff preview is usable only when keyed by severity cutoff "1".."5". */
function severityTradeoff(run: ModelRun | undefined): Record<number, { precision: number; recall: number }> | null {
  if (!run) return null
  const out: Record<number, { precision: number; recall: number }> = {}
  for (const n of [1, 2, 3, 4, 5]) {
    const p = run.tradeoff?.[String(n)]
    if (!p || typeof p.precision !== 'number' || typeof p.recall !== 'number') return null
    out[n] = p
  }
  return out
}

const fmt = (x: number | null | undefined) => (x === null || x === undefined ? '—' : x.toFixed(2))

export default function ModelPerformance() {
  const { threshold, setThreshold, saveThreshold, savedThreshold, thresholdVersion, feedbackSummary, refreshFeedback } = useStore()
  const { can } = useAuth()
  const [runs, setRuns] = useState<ModelRun[]>([])
  const [runsErr, setRunsErr] = useState<string | null>(null)
  const [runsLoaded, setRunsLoaded] = useState(false)
  const [runIdx, setRunIdx] = useState(0)
  const [picking, setPicking] = useState(false)
  const [saved, setSaved] = useState<Threshold | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [tuneMsg, setTuneMsg] = useState<{ ok: boolean; text: string } | null>(null)
  useEffect(() => {
    api.listRuns().then((r) => {
      setRuns(r)
      setRunsLoaded(true)
      const pub = r.findIndex((x) => x.published)
      setRunIdx(pub >= 0 ? pub : 0)
    }).catch((e) => setRunsErr(errorMessage(e)))
    void refreshFeedback()
  }, [refreshFeedback])
  const run = runs[runIdx] as ModelRun | undefined
  const tradeoff = severityTradeoff(run)
  const t = tradeoff?.[threshold]

  const correct = feedbackSummary?.correct ?? 0
  const incorrect = feedbackSummary?.incorrect ?? 0
  const missed = feedbackSummary?.missed ?? 0
  const total = feedbackSummary?.total ?? 0
  const minLabels = feedbackSummary?.minLabelsForFinetune ?? 50

  const save = async () => {
    setSaving(true); setSaveErr(null)
    try { setSaved(await saveThreshold()) } catch (e) { setSaveErr(errorMessage(e)) } finally { setSaving(false) }
  }
  const queueFineTune = async () => {
    setTuneMsg(null)
    try {
      const r = await api.queueFineTune()
      setTuneMsg({ ok: true, text: `Fine-tune request #${r.id} ${r.status} · ${r.labels} labels` })
    } catch (e) { setTuneMsg({ ok: false, text: errorMessage(e) }) }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-display text-xl font-bold uppercase tracking-wide">Model Performance</h1>
        <Eyebrow className="mt-3">Run</Eyebrow>
        {runsErr && <div className="mt-1 text-xs text-red-400">{runsErr}</div>}
        {!run ? (
          !runsErr && !runsLoaded && <div className="mt-1 text-sm text-text-muted">Loading…</div>
        ) : picking ? (
          <select autoFocus value={runIdx} onChange={(e) => { setRunIdx(Number(e.target.value)); setPicking(false) }} onBlur={() => setPicking(false)} className={`${inputCls} mt-1`}>
            {runs.map((r, i) => <option key={r.id} value={i}>{r.runId}, {r.split}</option>)}
          </select>
        ) : (
          <button onClick={() => setPicking(true)} className="mt-1 inline-flex items-center gap-4 rounded-lg border border-border-subtle bg-bg-primary px-3 py-1.5 text-sm transition-colors hover:border-text-muted focus:outline-none focus:ring-1 focus:ring-accent">
            <span>{run.runId}, {run.split}</span>
            {run.published && <Pill tone="green">published</Pill>}
            <span className="text-xs text-text-secondary">Change ›</span>
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-6">
          {runsLoaded && runs.length === 0 ? (
            <section className={`${cardCls} text-sm text-text-muted`}>No evaluated runs yet.</section>
          ) : (<>
          <div className="grid grid-cols-3 gap-4">
            <Kpi label="Precision" value={fmt(run?.precision)} />
            <Kpi label="Recall" value={fmt(run?.recall)} />
            <Kpi label="F1" value={fmt(run?.f1)} />
          </div>

          <section>
            <h2 className="mb-2 text-sm font-medium">Per defect</h2>
            <div className="overflow-hidden rounded-xl border border-border-subtle bg-bg-card">
              <table className="w-full text-xs">
                <thead className="bg-bg-card text-left text-[10px] uppercase tracking-wide text-text-muted">
                  <tr className="border-b border-border-subtle">
                    <th className="px-4 py-2 font-medium">Defect</th>
                    <th className="px-4 py-2 text-right font-medium">Precision</th>
                    <th className="px-4 py-2 text-right font-medium">Recall</th>
                    <th className="px-4 py-2 text-right font-medium">F1</th>
                    <th className="px-4 py-2 text-right font-medium">Support</th>
                  </tr>
                </thead>
                <tbody>
                  {DEFECT_TYPES.map((d, i) => {
                    const m = run?.perDefect?.[d] ?? { p: null, r: null, support: 0 }
                    const f1 = m.p !== null && m.r !== null ? (2 * m.p * m.r) / (m.p + m.r) : null
                    return (
                      <tr key={d} className="border-b border-border-subtle last:border-0 transition-colors hover:bg-bg-card-hover">
                        <td className="px-4 py-2"><span className="mr-2 inline-block h-2 w-2 rounded-sm align-middle" style={{ background: `var(--color-model-${i})` }} aria-hidden />{d}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{m.p === null ? <NA /> : m.p.toFixed(2)}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{m.r === null ? <NA /> : m.r.toFixed(2)}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{f1 === null ? <NA /> : f1.toFixed(2)}</td>
                        <td className="px-4 py-2 text-right tabular-nums text-text-secondary">{m.support}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
          </>)}

          <section className={cardCls}>
            <h2 className="text-sm font-medium">Feedback</h2>
            {total === 0 ? (
              <div className="mt-3 text-sm text-text-muted">
                No labels yet. <Link to="/" className="underline">Games</Link>
              </div>
            ) : (
              <>
                <div className="mt-3 grid grid-cols-4 gap-4">
                  <Mini label="Labels" value={total} />
                  <Mini label="Correct" value={correct} tone="text-green-400" />
                  <Mini label="Wrong" value={incorrect} tone="text-red-400" />
                  <Mini label="Missed" value={missed} tone="text-yellow-400" />
                </div>
                <div className="mt-3 flex h-2 gap-1" aria-hidden>
                  <div className="h-2 rounded-sm bg-green-500" style={{ flex: Math.max(correct, 0.05) }} />
                  <div className="h-2 rounded-sm bg-red-500" style={{ flex: Math.max(incorrect, 0.05) }} />
                  <div className="h-2 rounded-sm bg-yellow-500" style={{ flex: Math.max(missed, 0.05) }} />
                </div>
                <div className="mt-1 text-[11px] text-text-muted">
                  Observed precision {fmt(feedbackSummary?.observedPrecision)}
                </div>
                {can('reviewer') && <div className="mt-3 flex gap-2">
                  <a className={btnGhost} href={api.feedbackExportUrl} download="feedback.csv">Export CSV</a>
                  {can('admin') && <>
                    <button className={btnGhost} disabled={!feedbackSummary?.canQueueFinetune} onClick={queueFineTune}>Queue Fine-Tune</button>
                    {total < minLabels && <span className="self-center text-[11px] text-text-muted">{minLabels - total} more labels needed</span>}
                  </>}
                </div>}
                {tuneMsg && <div className={`mt-2 text-xs ${tuneMsg.ok ? 'text-green-400' : 'text-red-400'}`}>{tuneMsg.text}</div>}
              </>
            )}
          </section>
        </div>

        <div className="flex flex-col gap-6">
          {run && <section className={cardCls}>
            <h2 className="text-sm font-medium">Calibration</h2>
            {run && run.calibration.length > 1 ? <CalibrationCurve pts={run.calibration} /> : <div className="mt-3 text-sm text-text-muted">No calibration data for this run.</div>}
            <div className="mt-2 text-[11px] text-text-muted">Predicted probability →</div>
          </section>}

          <section className={cardCls}>
            <h2 className="text-sm font-medium">Alert threshold</h2>
            <div className="text-xs text-text-secondary" title={thresholdVersion ? `v${thresholdVersion.id}` : undefined}>Severity ≥ {savedThreshold}{threshold !== savedThreshold ? ` · previewing ${threshold}` : ''}</div>
            <div className="mt-4 grid grid-cols-3 gap-4">
              <div className="col-span-2">
                <input type="range" min={1} max={5} step={1} value={threshold} onChange={(e) => { setThreshold(Number(e.target.value)); setSaved(null) }} aria-label="Alert severity threshold" />
                <div className="mt-1 flex justify-between text-xs">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button key={n} onClick={() => { setThreshold(n); setSaved(null) }} className={`rounded px-1 tabular-nums transition-colors focus:outline-none focus:ring-1 focus:ring-accent ${n === threshold ? 'font-medium text-text-primary' : 'text-text-muted hover:text-text-primary'}`}>{n}</button>
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-border-subtle p-3">
                <Eyebrow>At severity {threshold}</Eyebrow>
                {t ? (
                  <>
                    <div className="mt-1 text-sm">Precision <span className="font-medium tabular-nums">{t.precision.toFixed(2)}</span></div>
                    <div className="text-sm">Recall <span className="font-medium tabular-nums">{t.recall.toFixed(2)}</span></div>
                  </>
                ) : (
                  <div className="mt-1 text-xs text-text-muted">No preview</div>
                )}
              </div>
            </div>
            {can('admin') && <div className="mt-4 flex items-center gap-3">
              <button className={btnPrimary} disabled={threshold === savedThreshold || saving} onClick={save}>Save</button>
              {saved && threshold === savedThreshold && <span className="text-xs text-green-400" title={`v${saved.id}${saved.modelId ? ` · ${saved.modelId}` : ''}`}>Saved</span>}
              {saveErr && <span className="text-xs text-red-400">{saveErr}</span>}
            </div>}
          </section>
        </div>
      </div>
    </div>
  )
}

function NA() {
  return <span className="text-text-muted" title="Not evaluated (too few labeled frames)">—</span>
}

function Mini({ label, value, tone = '' }: { label: string; value: number; tone?: string }) {
  return (
    <div>
      <Eyebrow>{label}</Eyebrow>
      <div className={`mt-0.5 font-display text-3xl font-bold tabular-nums ${tone}`}>{value}</div>
    </div>
  )
}

function CalibrationCurve({ pts }: { pts: number[][] }) {
  const W = 520, H = 220, px = 36, py = 12
  const sx = (x: number) => px + x * (W - px - 8)
  const sy = (y: number) => H - py - y * (H - py - 8)
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${sx(x)} ${sy(y)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full" role="img" aria-label="Calibration curve: observed frequency versus predicted probability">
      <line x1={sx(0)} y1={sy(0)} x2={sx(0)} y2={sy(1)} stroke="var(--color-border-subtle)" />
      <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(0)} stroke="var(--color-border-subtle)" />
      {[0.25, 0.5, 0.75, 1].map((g) => <line key={g} x1={sx(0)} y1={sy(g)} x2={sx(1)} y2={sy(g)} stroke="var(--color-border-subtle)" strokeDasharray="2 4" />)}
      {[0, 0.5, 1].map((g) => <text key={g} x={sx(0) - 6} y={sy(g) + 3} textAnchor="end" fontSize="10" fill="var(--color-text-muted)">{g.toFixed(1)}</text>)}
      <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="var(--color-text-muted)" strokeDasharray="4 4" />
      <path d={d} fill="none" stroke="var(--color-model-0)" strokeWidth="2" />
      {pts.map(([x, y]) => <circle key={x} cx={sx(x)} cy={sy(y)} r="2.5" fill="var(--color-model-0)" />)}
    </svg>
  )
}
