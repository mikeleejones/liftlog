import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'

type Accent = 'blue' | 'teal' | 'green' | 'indigo'

type HomeData = {
  sessions: { completed: number; required: number }
  deload: { active: boolean; deferred: boolean; weeks_to_next: number }
  in_progress: { workout_id: number; started_at: string; routine_name: string; accent: Accent } | null
  calendar: Array<Array<{
    date: string
    day_letter: string
    day_number: number
    accent: Accent | null
    is_today: boolean
    is_future: boolean
  }>>
  volume: {
    points: Array<{ value: number; is_pr: boolean; is_deload: boolean; label: string }>
    latest_kg: number | null
    latest_is_pr: boolean
  }
  progression: {
    ready: number
    stalled: number
    completed_weeks: number
    weeks_since_deload: number
    lifts: Array<{ id: number; name: string; last: string; next: string; suggest: string; kind: string }>
  }
  audit: { suggested_pct: number | null; working_sets: number }
}

function formatKg(value: number) {
  return Math.round(value).toLocaleString('en-US')
}

function VolumeChart({ points }: { points: HomeData['volume']['points'] }) {
  if (!points.length) return null

  const width = 680
  const height = 220
  const pad = { left: 40, right: 12, top: 12, bottom: 24 }
  let min = Math.min(...points.map((point) => point.value))
  let max = Math.max(...points.map((point) => point.value))
  if (min === max) { min -= 1; max += 1 }
  const x = (index: number) => points.length === 1
    ? pad.left + (width - pad.left - pad.right) / 2
    : pad.left + (width - pad.left - pad.right) * index / (points.length - 1)
  const y = (value: number) => pad.top + (height - pad.top - pad.bottom) * (1 - (value - min) / (max - min))

  return (
    <svg className="volume-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Total volume history">
      <text className="chart-label" x={pad.left - 7} y={y(max) + 4} textAnchor="end">{formatKg(max)}</text>
      <text className="chart-label" x={pad.left - 7} y={y(min) + 4} textAnchor="end">{formatKg(min)}</text>
      <line className="chart-baseline" x1={pad.left} x2={width - pad.right} y1={height - pad.bottom} y2={height - pad.bottom} />
      {points.slice(1).map((point, index) => (
        <line
          key={`${point.label}-${index}`}
          className={point.is_deload || points[index].is_deload ? 'chart-line is-deload' : 'chart-line'}
          x1={x(index)} y1={y(points[index].value)} x2={x(index + 1)} y2={y(point.value)}
        />
      ))}
      {points.filter((point) => point.is_pr || points.length === 1).map((point) => {
        const index = points.indexOf(point)
        return <circle key={`${point.label}-pr`} className="chart-dot" cx={x(index)} cy={y(point.value)} r="3.5" />
      })}
      <text className="chart-label" x={x(0)} y={height - 5} textAnchor="start">{points[0].label}</text>
      {points.length > 1 && <text className="chart-label" x={x(points.length - 1)} y={height - 5} textAnchor="end">{points.at(-1)?.label}</text>}
    </svg>
  )
}

export default function HomePage() {
  const queryClient = useQueryClient()
  const home = useQuery({ queryKey: ['home'], queryFn: () => api.get<HomeData>('/home') })
  const deferDeload = useMutation({
    mutationFn: () => api.post('/deload/defer'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['home'] }),
  })

  if (home.isLoading) return <div className="home-loading" aria-label="Loading Home" />
  if (!home.data) return <p className="load-error">Unable to load Home.</p>

  const { sessions, deload, in_progress: inProgress, calendar, volume, progression, audit } = home.data
  const dayLetters = calendar[0]?.map((cell) => cell.day_letter) ?? []

  return (
    <section className="home-page">
      <header className="home-header">
        <p className="section-label">liftlog</p>
        <p className="week-count">{sessions.completed} of {sessions.required} sessions this week</p>
      </header>

      {deload.active ? (
        <div className="home-card deload-banner">
          <div>
            <p className="deload-title">deload week - weights pre-set</p>
            <p className="card-meta">60% x 2x10, sessions excluded from progression</p>
          </div>
          <button className="quiet-button" type="button" disabled={deferDeload.isPending} onClick={() => deferDeload.mutate()}>
            defer
          </button>
        </div>
      ) : deload.deferred ? <div className="home-card muted-card">deload deferred - resumes next week</div> : null}

      {inProgress && (
        <Link className={`home-card resume-card accent-${inProgress.accent}`} to={`/workouts/${inProgress.workout_id}`}>
          <strong>{inProgress.routine_name}</strong>
          <span>workout in progress - tap to resume</span>
        </Link>
      )}

      <p className="section-label home-section">last 3 weeks</p>
      <div className="home-card calendar-card">
        <div className="calendar-row calendar-head">{dayLetters.map((letter, index) => <span key={`${letter}-${index}`}>{letter}</span>)}</div>
        {calendar.map((week, weekIndex) => (
          <div className="calendar-row" key={weekIndex}>
            {week.map((cell) => (
              <span
                className={`calendar-cell${cell.accent ? ` is-done accent-${cell.accent}` : ''}${cell.is_today ? ' is-today' : ''}${cell.is_future ? ' is-future' : ''}`}
                key={cell.date}
                title={`${cell.date}${cell.accent ? ' - session completed' : ''}`}
              >{cell.day_number}</span>
            ))}
          </div>
        ))}
      </div>

      {volume.latest_kg !== null && (
        <>
          <p className="section-label home-section">total volume - kg</p>
          <div className="home-card chart-card">
            <div className="volume-head">
              <strong>{formatKg(volume.latest_kg)}<small> kg</small></strong>
              {volume.latest_is_pr && <span className="progress-chip">volume PR</span>}
            </div>
            <VolumeChart points={volume.points} />
            <p className="chart-legend">● PR - dashed = deload</p>
          </div>
        </>
      )}

      <p className="section-label home-section">progression</p>
      <div className="stat-grid">
        <Stat value={progression.ready} label="ready to progress" accent={progression.ready ? 'green' : undefined} />
        <Stat value={progression.stalled} label="stalled" accent={progression.stalled ? 'teal' : undefined} />
        <Stat value={progression.completed_weeks} label="weeks done" />
        <Stat value={deload.active ? 'now' : deload.weeks_to_next} label={deload.active ? 'deload week' : 'weeks to deload'} accent={deload.active ? 'teal' : undefined} />
      </div>

      {!!progression.lifts.length && <>
        <p className="section-label home-section">lifts this week</p>
        <div className="lift-list">
          {progression.lifts.map((lift) => (
            <Link className="home-card lift-row" to={`/exercises/${lift.id}`} key={lift.id}>
              <div className="lift-title"><strong>{lift.name}</strong>{lift.kind === 'progress' && <span className="progress-chip">up {lift.suggest}</span>}{lift.kind === 'stall' && <span className="stall-chip">stalled: try {lift.suggest}</span>}</div>
              <span>last {lift.last} - next {lift.next}</span>
            </Link>
          ))}
        </div>
      </>}

      {audit.suggested_pct !== null && <>
        <p className="section-label home-section">honesty audit</p>
        <div className="home-card audit-card">
          {audit.suggested_pct}% of {audit.working_sets} working sets logged as-suggested
          {audit.suggested_pct >= 95 && <span>high - check that logging reflects what you actually lifted</span>}
        </div>
      </>}
    </section>
  )
}

function Stat({ value, label, accent }: { value: string | number; label: string; accent?: Accent }) {
  return <div className="home-card stat-tile"><strong className={accent ? `accent-text-${accent}` : ''}>{value}</strong><span>{label}</span></div>
}
