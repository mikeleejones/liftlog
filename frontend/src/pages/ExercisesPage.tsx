import { useDeferredValue, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'

type Exercise = {
  id: number
  name: string
  movement_pattern: string
  muscle_group: string
  increment_kg: number
  display_unit: string
  cue: string | null
}

export default function ExercisesPage() {
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query)
  const exercises = useQuery({
    queryKey: ['exercises', deferredQuery],
    queryFn: () => api.get<{ query: string; exercises: Exercise[] }>(`/exercises?q=${encodeURIComponent(deferredQuery)}`),
  })
  const rows = exercises.data?.exercises ?? []

  return <section className="exercises-page">
    <header className="exercise-library-header"><p className="section-label">exercise library</p><p>{rows.length} exercise{rows.length === 1 ? '' : 's'}{deferredQuery ? ` matching "${deferredQuery}"` : ''}</p></header>
    <label className="sr-only" htmlFor="exercise-search">Search by name</label>
    <input id="exercise-search" className="exercise-search" type="search" placeholder="search by name" autoComplete="off" spellCheck="false" value={query} onChange={(event) => setQuery(event.target.value)} />
    {exercises.isLoading ? <div className="exercise-loading" aria-label="Loading exercises" /> : rows.length ? <div className="exercise-list">{rows.map((exercise) => <Link className="exercise-card" key={exercise.id} to={`/exercises/${exercise.id}`}><strong>{exercise.name}</strong><span>{exercise.movement_pattern} - {exercise.muscle_group} - +{exercise.increment_kg} kg - {exercise.display_unit}</span>{exercise.cue && <em>{exercise.cue}</em>}</Link>)}</div> : <div className="empty-routines">{deferredQuery ? `no exercises match "${deferredQuery}"` : 'no exercises yet'}</div>}
  </section>
}
