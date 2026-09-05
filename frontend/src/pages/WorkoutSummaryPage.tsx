import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '@/lib/api'

type Summary = {
  workout: { id: number; finished_at: string | null; routine_name: string; accent: string; duration_seconds: number }
  totals: { sets: number; volume_kg: number }
  exercises: Array<{ exercise_id: number; name: string; unit: string; sets: Array<{ text: string }> }>
}

function duration(seconds: number) { return `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}` }
function volume(kg: number) { return `${Math.round(kg).toLocaleString()} kg` }

export default function WorkoutSummaryPage() {
  const { workoutId } = useParams()
  const summary = useQuery({ queryKey: ['workout-summary', workoutId], queryFn: () => api.get<Summary>(`/workouts/${workoutId}/summary`) })
  if (summary.isLoading) return <div className="workout-loading" aria-label="Loading summary" />
  if (!summary.data) return <p className="load-error">Workout not found.</p>
  const { workout, totals, exercises } = summary.data
  return <section className="summary-page">
    <header className="summary-header"><p className="section-label">workout complete</p><h1 className={`accent-text-${workout.accent}`}>{workout.routine_name}</h1></header>
    <div className="summary-card"><div><span>duration</span>{duration(workout.duration_seconds)}</div><div><span>sets</span>{totals.sets}</div><div><span>volume</span>{volume(totals.volume_kg)}</div></div>
    <p className="section-label workout-section">sets</p>
    {exercises.length ? exercises.map((exercise) => <Link className="summary-exercise" key={exercise.exercise_id} to={`/exercises/${exercise.exercise_id}`}><strong>{exercise.name}</strong><span>{exercise.sets.map((set) => set.text).join(' · ')} {exercise.unit}</span></Link>) : <div className="empty-routines">no sets logged</div>}
    {workout.finished_at && <a className="summary-export" href={`/workout/${workout.id}/export.tcx`}>EXPORT TO HEALTH (.TCX)</a>}
    <Link className={`start-button accent-fill-${workout.accent}`} to="/">HOME</Link>
  </section>
}
