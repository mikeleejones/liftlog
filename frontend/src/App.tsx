import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from '@/components/layout/AppShell'
import ExerciseDetailPage from '@/pages/ExerciseDetailPage'
import ExercisesPage from '@/pages/ExercisesPage'
import ProtectedLayout from '@/components/layout/ProtectedLayout'
import HomePage from '@/pages/HomePage'
import LoginPage from '@/pages/LoginPage'
import ProfilePage from '@/pages/ProfilePage'
import RoutinePreviewPage from '@/pages/RoutinePreviewPage'
import WorkoutPage from '@/pages/WorkoutPage'
import ActiveWorkoutPage from '@/pages/ActiveWorkoutPage'
import WorkoutSummaryPage from '@/pages/WorkoutSummaryPage'
import ProgramBuilderPage from '@/pages/ProgramBuilderPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedLayout />}>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="/routines" element={<WorkoutPage />} />
          <Route path="/routines/new" element={<ProgramBuilderPage />} />
          <Route path="/routines/:routineId/preview" element={<RoutinePreviewPage />} />
          <Route path="/exercises" element={<ExercisesPage />} />
          <Route path="/exercises/:exerciseId" element={<ExerciseDetailPage />} />
          <Route path="/settings" element={<ProfilePage />} />
          <Route path="/workouts/:workoutId/summary" element={<WorkoutSummaryPage />} />
        </Route>
        <Route path="/workouts/:workoutId" element={<ActiveWorkoutPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
