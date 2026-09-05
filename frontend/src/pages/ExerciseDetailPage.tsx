import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '@/lib/api'

type Axis = 'weight' | 'reps' | 'duration' | 'distance'
type ExerciseType = 'weight_reps' | 'reps_only' | 'duration' | 'duration_weight' | 'distance' | 'distance_weight' | 'none'
type Metrics = { id: number; text: string; weight_kg: number | null; reps: number | null; duration_seconds: number | null; distance_m: number | null }
type Detail = {
  exercise: { id: number; name: string; movement_pattern: string; muscle_group: string; exercise_type: ExerciseType; display_unit: string; youtube_query: string; progress_reset_at: string | null }
  unit: string
  editable: boolean
  chart_points: Array<{ value: number; is_pr: boolean; is_deload: boolean; label: string }>
  history: Array<{ date: string; is_deload: boolean; is_pr: boolean; top: string; sets: Metrics[] }>
}

const axes: Record<ExerciseType, Axis[]> = {
  weight_reps: ['weight', 'reps'], reps_only: ['reps'], duration: ['duration'], duration_weight: ['weight', 'duration'], distance: ['distance'], distance_weight: ['distance', 'weight'], none: [],
}
const KG_PER_LB = 0.45359237
const M_PER_MI = 1609.344

function chartGeometry(points: Detail['chart_points']) {
  const width = 680; const height = 220; const pad = { left: 40, right: 12, top: 12, bottom: 24 }
  let min = Math.min(...points.map((point) => point.value)); let max = Math.max(...points.map((point) => point.value))
  if (min === max) { min -= 1; max += 1 }
  const x = (index: number) => points.length === 1 ? pad.left + (width - pad.left - pad.right) / 2 : pad.left + (width - pad.left - pad.right) * index / (points.length - 1)
  const y = (value: number) => pad.top + (height - pad.top - pad.bottom) * (1 - (value - min) / (max - min))
  return { width, height, pad, min, max, x, y }
}

function DetailChart({ points }: { points: Detail['chart_points'] }) {
  if (!points.length) return null
  const { width, height, pad, min, max, x, y } = chartGeometry(points)
  return <svg className="volume-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Exercise history chart">
    <text className="chart-label" x={pad.left - 7} y={y(max) + 4} textAnchor="end">{Math.round(max * 10) / 10}</text><text className="chart-label" x={pad.left - 7} y={y(min) + 4} textAnchor="end">{Math.round(min * 10) / 10}</text>
    <line className="chart-baseline" x1={pad.left} x2={width - pad.right} y1={height - pad.bottom} y2={height - pad.bottom} />
    {points.slice(1).map((point, index) => <line key={`${point.label}-${index}`} className={point.is_deload || points[index].is_deload ? 'chart-line is-deload' : 'chart-line'} x1={x(index)} y1={y(points[index].value)} x2={x(index + 1)} y2={y(point.value)} />)}
    {points.filter((point) => point.is_pr || points.length === 1).map((point) => <circle key={`${point.label}-pr`} className="chart-dot" cx={x(points.indexOf(point))} cy={y(point.value)} r="3.5" />)}
    <text className="chart-label" x={x(0)} y={height - 5} textAnchor="start">{points[0].label}</text>{points.length > 1 && <text className="chart-label" x={x(points.length - 1)} y={height - 5} textAnchor="end">{points.at(-1)?.label}</text>}
  </svg>
}

export default function ExerciseDetailPage() {
  const { exerciseId } = useParams()
  const queryClient = useQueryClient()
  const [resetOpen, setResetOpen] = useState(false)
  const [editing, setEditing] = useState<Metrics | null>(null)
  const detail = useQuery({ queryKey: ['exercise', exerciseId], queryFn: () => api.get<Detail>(`/exercises/${exerciseId}`) })
  const reset = useMutation({ mutationFn: () => api.post(`/exercises/${exerciseId}/reset-progress`), onSuccess: () => { setResetOpen(false); queryClient.invalidateQueries({ queryKey: ['exercise', exerciseId] }) } })
  const save = useMutation({ mutationFn: (set: Metrics) => api.post(`/set/${set.id}`, metricBody(set, detail.data?.exercise.exercise_type ?? 'none')), onSuccess: () => { setEditing(null); queryClient.invalidateQueries({ queryKey: ['exercise', exerciseId] }) } })

  if (detail.isLoading) return <div className="exercise-loading" aria-label="Loading exercise" />
  if (!detail.data) return <p className="load-error">Exercise not found.</p>
  const { exercise, unit, history, chart_points: chartPoints } = detail.data
  const actionFailure = reset.error ?? save.error
  const actionError = actionFailure instanceof ApiError ? actionFailure.message : null

  return <section className="exercise-detail-page">
    <header className="exercise-detail-header"><div><p className="section-label">exercise</p><h1>{exercise.name}</h1><p>{exercise.movement_pattern} - {exercise.muscle_group}</p></div><Link to="/exercises">exercises</Link></header>
    <div className="exercise-detail-actions"><a href={`https://www.youtube.com/results?search_query=${encodeURIComponent(exercise.youtube_query)}`} target="_blank" rel="noreferrer">demo</a><button type="button" onClick={() => setResetOpen(true)}>reset progress</button></div>
    {exercise.progress_reset_at && <p className="reset-note">suggestions reset {exercise.progress_reset_at.slice(0, 10)} - history below is unaffected</p>}
    {chartPoints.length ? <div className="detail-chart-card"><p className="section-label">top set - {unit}</p><DetailChart points={chartPoints} /><p className="chart-legend">● PR - dashed = deload</p></div> : <div className="empty-routines">no history yet</div>}
    {!!history.length && <><p className="section-label exercise-history-label">history</p><div className="exercise-history">{[...history].reverse().map((session) => <article className={`history-card${session.is_pr ? ' is-pr' : ''}`} key={session.date}><div className="history-head"><span>{session.date}{session.is_deload ? ' deload' : ''}</span><span>{session.is_pr ? <em className="progress-chip">PR {session.top}</em> : <>top {session.top} {unit}</>}</span></div><div className="history-sets">{session.sets.map((set) => detail.data?.editable ? <button type="button" key={set.id} onClick={() => setEditing(set)}>{set.text}</button> : <span key={set.id}>{set.text}</span>)}</div></article>)}</div></>}
    {actionError && <p className="action-error">{actionError}</p>}
    {resetOpen && <div className="delete-sheet" role="dialog" aria-modal="true"><p className="section-label">reset progress</p><p>history stays visible. Weight and rep suggestions start fresh from your next session.</p><button className="reset-button" type="button" disabled={reset.isPending} onClick={() => reset.mutate()}>RESET PROGRESS</button><button className="cancel-button" type="button" onClick={() => setResetOpen(false)}>cancel</button></div>}
    {editing && <SetEditor set={editing} exercise={exercise} saving={save.isPending} onChange={setEditing} onCancel={() => setEditing(null)} onSave={() => save.mutate(editing)} />}
  </section>
}

function metricBody(set: Metrics, type: ExerciseType) {
  const used = axes[type]
  return { weight_kg: used.includes('weight') ? set.weight_kg : null, reps: used.includes('reps') ? set.reps : null, duration_seconds: used.includes('duration') ? set.duration_seconds : null, distance_m: used.includes('distance') ? set.distance_m : null }
}

function SetEditor({ set, exercise, saving, onChange, onCancel, onSave }: { set: Metrics; exercise: Detail['exercise']; saving: boolean; onChange: (set: Metrics) => void; onCancel: () => void; onSave: () => void }) {
  const activeAxes = axes[exercise.exercise_type]
  const adjust = (axis: Axis, direction: number) => {
    if (axis === 'weight') { const displayUnit = exercise.exercise_type === 'distance_weight' ? 'kg' : exercise.display_unit; const step = displayUnit === 'lbs' ? 5 * KG_PER_LB : 2.5; onChange({ ...set, weight_kg: Math.max(0, (set.weight_kg ?? 0) + direction * step) }) }
    if (axis === 'reps') onChange({ ...set, reps: Math.max(1, (set.reps ?? 1) + direction) })
    if (axis === 'duration') onChange({ ...set, duration_seconds: Math.max(0, (set.duration_seconds ?? 0) + direction * 5) })
    if (axis === 'distance') { const step = exercise.display_unit === 'mi' ? M_PER_MI / 10 : 100; onChange({ ...set, distance_m: Math.max(0, (set.distance_m ?? 0) + direction * step) }) }
  }
  return <div className="delete-sheet set-editor" role="dialog" aria-modal="true"><p className="section-label">edit set</p><p>correcting a logged set - it stays in the same slot</p><div className="edit-axes">{activeAxes.map((axis) => <Stepper key={axis} axis={axis} set={set} exercise={exercise} onAdjust={adjust} />)}</div><button className="save-button" type="button" disabled={saving} onClick={onSave}>SAVE CHANGES</button><button className="cancel-button" type="button" onClick={onCancel}>cancel</button></div>
}

function Stepper({ axis, set, exercise, onAdjust }: { axis: Axis; set: Metrics; exercise: Detail['exercise']; onAdjust: (axis: Axis, direction: number) => void }) {
  let value = ''; let label: string = axis
  if (axis === 'weight') { const displayUnit = exercise.exercise_type === 'distance_weight' ? 'kg' : exercise.display_unit; value = `${round(displayUnit === 'lbs' ? (set.weight_kg ?? 0) / KG_PER_LB : set.weight_kg ?? 0)} ${displayUnit}`; label = `weight (${displayUnit})` }
  if (axis === 'reps') value = String(set.reps ?? 1)
  if (axis === 'duration') value = seconds(set.duration_seconds ?? 0)
  if (axis === 'distance') { const unit = exercise.display_unit; value = `${round(unit === 'mi' ? (set.distance_m ?? 0) / M_PER_MI : (set.distance_m ?? 0) / 1000)} ${unit}`; label = `distance (${unit})` }
  if (axis === 'duration') label = 'time'
  return <div><div className="set-stepper"><button type="button" onClick={() => onAdjust(axis, -1)}>-</button><strong>{value}</strong><button type="button" onClick={() => onAdjust(axis, 1)}>+</button></div><span>{label}</span></div>
}

function round(value: number) { return Math.round(value * 100) / 100 }
function seconds(value: number) { return `${Math.floor(value / 60)}:${String(Math.round(value % 60)).padStart(2, '0')}` }
