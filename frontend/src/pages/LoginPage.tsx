import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '@/lib/api'
import { useAuthSession } from '@/lib/auth'

export default function LoginPage() {
  const [secret, setSecret] = useState('')
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const session = useAuthSession()
  const login = useMutation({
    mutationFn: () => api.post<{ authenticated: boolean }>('/auth/login', { secret }),
    onSuccess: (data) => {
      queryClient.setQueryData(['auth-session'], data)
      const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname || '/'
      navigate(from, { replace: true })
    },
  })

  if (session.data?.authenticated) return <Navigate to="/" replace />

  return (
    <main className="login-page">
      <form className="login-form" onSubmit={(event) => { event.preventDefault(); login.mutate() }}>
        <p className="section-label">liftlog</p>
        <label className="sr-only" htmlFor="secret">Secret</label>
        <input
          id="secret"
          className="secret-input"
          type="password"
          placeholder="secret"
          autoComplete="current-password"
          autoFocus
          value={secret}
          onChange={(event) => setSecret(event.target.value)}
          disabled={login.isPending}
        />
        {login.error instanceof ApiError && <p className="login-error">wrong secret</p>}
        <button className="login-submit" type="submit" disabled={login.isPending || !secret}>
          {login.isPending ? 'ENTERING' : 'ENTER'}
        </button>
      </form>
    </main>
  )
}
