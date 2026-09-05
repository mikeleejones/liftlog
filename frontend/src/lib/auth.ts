import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export type AuthSession = { authenticated: boolean }

export function useAuthSession() {
  return useQuery({
    queryKey: ['auth-session'],
    queryFn: () => api.get<AuthSession>('/auth/session'),
    staleTime: Infinity,
  })
}
