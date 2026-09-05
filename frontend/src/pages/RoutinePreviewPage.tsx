import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '@/lib/api'

type RoutinePreview = {
  routine: { id: number; name: string; accent: 'blue' | 'teal' | 'green' | 'indigo' }
  exercises: Array<{ exercise_id: number; name: string; cue: string | null; is_primary: boolean; target: string }>
}

export default function RoutinePreviewPage() {
  const { routineId } = useParams()
  const navigate = useNavigate()
  const preview = useQuery({ queryKey: ['routine-preview', routineId], queryFn: () => api.get<RoutinePreview>(`/routines/${routineId}/preview`) })
  const start = useMutation({ mutationFn: () => api.post<{ id: number }>('/workouts', { routine_id: Number(routineId) }), onSuccess: ({ id }) => navigate(`/workouts/${id}`) })

  if (preview.isLoading) return <div className="workout-loading" aria-label="Loading routine preview" />
  if (!preview.data) return <p className="load-error">Routine not found.</p>
  const { routine, exercises } = preview.data
  const error = start.error instanceof ApiError ? start.error.message : null

  return <section className="routine-preview-page">
    <header className="preview-header"><div><p className="section-label">routine preview</p><h1 className={`accent-text-${routine.accent}`}>{routine.name}</h1><p>{exercises.length} exercise{exercises.length === 1 ? '' : 's'} - read-only</p></div><Link to="/routines">workout</Link></header>
    {exercises.map((exercise, index) => <article className="preview-exercise" key={exercise.exercise_id}><div><strong>{index + 1}. {exercise.name}</strong>{exercise.is_primary && <span>primary</span>}</div><p>{exercise.target}</p>{exercise.cue && <p className="exercise-cue">{exercise.cue}</p>}</article>)}
    {!exercises.length && <div className="empty-routines">this routine has no exercises</div>}
    {error && <p className="action-error">{error}</p>}
    <button className={`start-button accent-fill-${routine.accent}`} type="button" disabled={start.isPending} onClick={() => start.mutate()}>START</button>
    <p className="preview-note">previewing changes nothing - start creates the session.</p>
  </section>
}
