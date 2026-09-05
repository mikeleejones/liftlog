import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuthSession } from '@/lib/auth'

export default function ProtectedLayout() {
  const location = useLocation()
  const { data, isLoading } = useAuthSession()

  if (isLoading) return <div className="bootstrap" aria-label="Loading" />
  if (!data?.authenticated) return <Navigate to="/login" replace state={{ from: location }} />
  return <Outlet />
}
