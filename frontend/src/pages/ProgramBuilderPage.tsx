import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '@/lib/api'
import ProgramPlanPreview, { type ProgramPlan } from '@/components/ProgramPlanPreview'

type Message = { role: 'user' | 'assistant'; content: string }
type Draft = { messages: Message[]; plan: ProgramPlan | null }
type Turn = { state: 'ok' | 'limit' | 'error'; message: string; plan: ProgramPlan | null }

export default function ProgramBuilderPage() {
  const [content, setContent] = useState('')
  const latestMessage = useRef<HTMLDivElement>(null)
  const previousMessageCount = useRef<number | null>(null)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const draft = useQuery({ queryKey: ['program-builder'], queryFn: () => api.get<Draft>('/programs/builder') })
  const send = useMutation({ mutationFn: (message: string) => api.post<Turn>('/programs/builder/message', { content: message }), onSuccess: () => { setContent(''); queryClient.invalidateQueries({ queryKey: ['program-builder'] }) } })
  const apply = useMutation({ mutationFn: () => api.post<{ result?: ProgramPlan; errors?: string[] }>('/programs/builder/apply'), onSuccess: (response) => { if (response.errors) return; queryClient.invalidateQueries({ queryKey: ['routines'] }); queryClient.invalidateQueries({ queryKey: ['home'] }); queryClient.invalidateQueries({ queryKey: ['program-builder'] }); navigate('/routines') } })
  const discard = useMutation({ mutationFn: () => api.post('/programs/builder/discard'), onSuccess: () => { setContent(''); queryClient.invalidateQueries({ queryKey: ['program-builder'] }) } })
  const messages = draft.data?.messages ?? []
  useEffect(() => {
    if (!draft.data) return
    if (previousMessageCount.current !== null && messages.length > previousMessageCount.current) latestMessage.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    previousMessageCount.current = messages.length
  }, [draft.data, messages.length])
  if (draft.isLoading) return <div className="workout-loading" aria-label="Loading program builder" />
  if (!draft.data) return <p className="load-error">Unable to load program builder.</p>
  const error = [send.error, apply.error, discard.error].find((item) => item instanceof ApiError) as ApiError | undefined
  return <section className="builder-page"><header className="builder-header"><div><p className="section-label">new program</p><h1>describe what you want to train</h1></div><Link className="quiet-button" to="/routines">close</Link></header><p className="builder-intro">Tell the builder your goal, days available, equipment, experience, and any constraints. Refine the plan together before applying it.</p><div className="builder-chat" aria-live="polite">{messages.length ? messages.map((message, index) => <div className={`builder-message ${message.role}`} key={`${message.role}-${index}`} ref={index === messages.length - 1 ? latestMessage : null}><span>{message.role === 'assistant' ? 'builder' : 'you'}</span><p>{message.content}</p></div>) : <div className="builder-empty"><strong>start with the basics</strong><p>Example: &quot;I want a three-day strength program using a barbell and dumbbells. I have trained for a year and want to prioritize legs without aggravating my lower back.&quot;</p></div>}{send.data && send.data.state !== 'ok' && <div className="builder-message system"><span>builder</span><p>{send.data.message}</p></div>}</div>{draft.data.plan && <ProgramPlanPreview plan={draft.data.plan} applying={apply.isPending} onApply={() => apply.mutate()} />}{apply.data?.errors && <p className="action-error">{apply.data.errors.join(' ')}</p>}{error && <p className="action-error">{error.message}</p>}<div className="builder-actions">{messages.length > 0 && <button className="quiet-button danger" type="button" disabled={discard.isPending} onClick={() => discard.mutate()}>start over</button>}</div><form className="builder-compose" onSubmit={(event) => { event.preventDefault(); if (content.trim()) send.mutate(content) }}><textarea value={content} onChange={(event) => setContent(event.target.value)} rows={3} maxLength={4000} placeholder="Describe your program or refine the draft..." disabled={send.isPending} /><button className="profile-primary" type="submit" disabled={send.isPending || !content.trim()}>{send.isPending ? 'THINKING...' : 'SEND'}</button></form></section>
}
