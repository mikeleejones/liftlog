import { Dumbbell, House, UserRound, Waves } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

const tabs = [
  { to: '/', label: 'home', icon: House, end: true },
  { to: '/routines', label: 'workout', icon: Dumbbell },
  { to: '/exercises', label: 'exercises', icon: Waves },
  { to: '/settings', label: 'profile', icon: UserRound },
]

export default function AppShell() {
  const home = useQuery({ queryKey: ['home'], queryFn: () => api.get<HomeState>('/home'), refetchInterval: 15_000 })
  const inProgress = home.data?.in_progress
  return (
    <div className={`app-shell${inProgress ? ' has-mini-session' : ''}`}>
      <main className="content"><Outlet /></main>
      {inProgress && <MiniSession workout={inProgress} />}
      <nav className="tab-bar" aria-label="Primary navigation">
        {tabs.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className="tab-link">
            <Icon aria-hidden="true" size={19} strokeWidth={1.8} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

type HomeState = { in_progress: { workout_id: number; started_at: string; routine_name: string; accent: 'blue' | 'teal' | 'green' | 'indigo' } | null }
type SavedRest = { workoutId?: number; restEndsAt?: number; restTotal?: number }

function MiniSession({ workout }: { workout: NonNullable<HomeState['in_progress']> }) {
  const [saved] = useState(() => { try { return JSON.parse(localStorage.getItem('liftlog.session') ?? '{}') as SavedRest } catch { return {} } })
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date().getTime()), 1_000); return () => window.clearInterval(timer) }, [])
  const rest = saved.workoutId === workout.workout_id && (saved.restEndsAt ?? 0) > now ? saved.restEndsAt! - now : 0
  const elapsed = Math.max(0, now - new Date(workout.started_at).getTime())
  return <NavLink className={`mini-session accent-${workout.accent}`} to={`/workouts/${workout.workout_id}`} aria-label={`Resume ${workout.routine_name}`}><span>{workout.routine_name}</span><strong>{rest ? `${restText(rest)} rest` : elapsedText(elapsed)}</strong><em>resume</em></NavLink>
}

function restText(milliseconds: number) { const seconds = Math.ceil(milliseconds / 1000); return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` }
function elapsedText(milliseconds: number) { const seconds = Math.floor(milliseconds / 1000); return `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}` }
