import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '@/lib/api'

type Accent = 'blue' | 'teal' | 'green' | 'indigo'

type Routine = {
  id: number
  name: string
  exercise_count: number
  accent: Accent
  progress_ready?: number
}

type Program = {
  id: number
  name: string
  weeks_count: number
  is_active: boolean
  current_week: number
  weeks: Array<{ number: number; routines: Routine[] }>
}

type RoutineList = {
  view: 'active' | 'archived'
  programs: Program[]
  standalone: Routine[]
  quick_start?: Routine[]
  deload_active?: boolean
}

export default function WorkoutPage() {
  const navigate = useNavigate()
  const [view, setView] = useState<'active' | 'archived'>('active')
  const [confirming, setConfirming] = useState<Routine | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const routines = useQuery({
    queryKey: ['routines', view],
    queryFn: () => api.get<RoutineList>(`/routines?view=${view}`),
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['routines'] })
  const mutation = useMutation({
    mutationFn: async ({ action, id }: { action: 'activate' | 'archive' | 'reactivate' | 'delete'; id: number }) => {
      if (action === 'delete') return api.delete(`/routines/${id}`)
      if (action === 'activate') return api.post(`/programs/${id}/activate`)
      return api.post(`/routines/${id}/${action}`)
    },
    onSuccess: () => { setActionError(null); setConfirming(null); refresh() },
    onError: (error) => setActionError(error instanceof ApiError ? error.message : 'Request failed'),
  })
  const start = useMutation({
    mutationFn: (routineId: number) => api.post<{ id: number }>('/workouts', { routine_id: routineId }),
    onSuccess: ({ id }) => navigate(`/workouts/${id}`),
    onError: (error) => setActionError(error instanceof ApiError ? error.message : 'Could not start workout'),
  })

  if (routines.isLoading) return <div className="workout-loading" aria-label="Loading Workout" />
  if (!routines.data) return <p className="load-error">Unable to load Workout.</p>

  const data = routines.data
  const activeProgram = data.programs.find((program) => program.is_active)
  return (
    <section className="workout-page">
      <header className="workout-header">
        <div><p className="section-label">workout</p><p className="workout-meta">{data.programs.length} program{data.programs.length === 1 ? '' : 's'} - start a session</p></div>
        <Link className="quiet-button" to="/routines/new">new program</Link>
      </header>

      <div className="view-tabs" role="tablist" aria-label="Routine view">
        {(['active', 'archived'] as const).map((candidate) => <button key={candidate} type="button" className={view === candidate ? 'is-active' : ''} onClick={() => { setView(candidate); setConfirming(null) }}>{candidate}</button>)}
      </div>
      {actionError && <p className="action-error">{actionError}</p>}

      {view === 'active' && data.quick_start?.length ? <>
        <p className="section-label workout-section">start a session{activeProgram && activeProgram.weeks_count > 1 ? ` - week ${activeProgram.current_week} of ${activeProgram.weeks_count}` : ''}</p>
        {data.quick_start.map((routine) => (
          <div className={`routine-card accent-${routine.accent}`} key={routine.id}>
            <Link to={`/routines/${routine.id}/preview`}>
              <div className="routine-card-title"><strong>{routine.name}</strong>{routine.progress_ready && !data.deload_active ? <span className="progress-chip">{routine.progress_ready} lift{routine.progress_ready === 1 ? '' : 's'} ready ↑</span> : null}</div>
              <span>{routine.exercise_count} exercises - tap to preview</span>
            </Link>
            <button className={`start-button accent-fill-${routine.accent}`} type="button" disabled={start.isPending} onClick={() => start.mutate(routine.id)}>START</button>
          </div>
        ))}
        <p className="section-label workout-section">programs</p>
      </> : null}

      {data.programs.length ? data.programs.map((program) => (
        <div className={`program-card${program.is_active && view === 'active' ? ' is-active' : ''}`} key={program.id}>
          <div className="program-head">
            <div><strong>{program.name}</strong><span>{program.is_active ? `active${program.weeks_count > 1 ? ` - week ${program.current_week} of ${program.weeks_count}` : ''}` : `${program.weeks_count} week cycle`}</span></div>
            {view === 'active' && !program.is_active && <button className="quiet-button" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate({ action: 'activate', id: program.id })}>activate</button>}
          </div>
          {program.weeks.map((week) => <div key={week.number}>
            {program.weeks_count > 1 && <p className="section-label week-label">week {week.number}</p>}
            <RoutineLines routines={week.routines} archived={view === 'archived'} active={program.is_active} onArchive={(id) => mutation.mutate({ action: 'archive', id })} onReactivate={(id) => mutation.mutate({ action: 'reactivate', id })} onDelete={setConfirming} />
          </div>)}
        </div>
      )) : <div className="empty-routines">{view === 'archived' ? 'no archived routines' : 'no programs yet - build one with AI'}</div>}

      {!!data.standalone.length && <>
        <p className="section-label workout-section">standalone routines</p>
        <div className="program-card"><RoutineLines routines={data.standalone} archived={view === 'archived'} onArchive={(id) => mutation.mutate({ action: 'archive', id })} onReactivate={(id) => mutation.mutate({ action: 'reactivate', id })} onDelete={setConfirming} /></div>
      </>}

      {confirming && <div className="delete-sheet" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <p id="delete-title" className="section-label">delete routine</p>
        <p>delete &quot;{confirming.name}&quot; and its prescription?</p>
        <p>logged workouts are kept as ad-hoc sessions - no history is lost.</p>
        <button className="delete-button" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate({ action: 'delete', id: confirming.id })}>DELETE ROUTINE</button>
        <button className="cancel-button" type="button" onClick={() => setConfirming(null)}>cancel</button>
      </div>}
    </section>
  )
}

function RoutineLines({ routines, archived, active, onArchive, onReactivate, onDelete }: { routines: Routine[]; archived: boolean; active?: boolean; onArchive: (id: number) => void; onReactivate: (id: number) => void; onDelete: (routine: Routine) => void }) {
  return <div className="routine-lines">{routines.map((routine) => <div className="routine-line" key={routine.id}>
    {archived ? <strong>{routine.name}</strong> : <Link className={active ? `accent-text-${routine.accent}` : ''} to={`/routines/${routine.id}/preview`}>{routine.name}</Link>}
    <span className="routine-actions"><small>{routine.exercise_count} exercises</small>{archived ? <button className="quiet-button" type="button" onClick={() => onReactivate(routine.id)}>reactivate</button> : <><button className="quiet-button" type="button" onClick={() => onArchive(routine.id)}>archive</button><button className="quiet-button danger" type="button" onClick={() => onDelete(routine)}>delete</button></>}</span>
  </div>)}</div>
}
