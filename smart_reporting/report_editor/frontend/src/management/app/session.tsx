import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { sessionSchema, type Session } from '../api/contracts'
import {
  request,
  advanceSession,
  sessionEpoch,
  setUnauthorized,
  ApiError,
} from '../api/http'
type State = {
  status: 'loading' | 'anonymous' | 'authenticated' | 'unavailable'
  session: Session | null
  error: string
}
const Context = createContext<{
  state: State
  load: () => Promise<void>
  clear: (message?: string) => void
}>(null!)
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const client = useQueryClient(),
    [state, setState] = useState<State>({
      status: 'loading',
      session: null,
      error: '',
    })
  const clear = useCallback(
    (message = '') => {
      advanceSession()
      client.clear()
      setState({ status: 'anonymous', session: null, error: message })
    },
    [client],
  )
  const load = useCallback(async () => {
    const started = sessionEpoch()
    try {
      const session = await request('/me', sessionSchema)
      setState({ status: 'authenticated', session, error: '' })
    } catch (e) {
      if (
        started !== sessionEpoch() ||
        (e instanceof DOMException && e.name === 'AbortError')
      )
        return
      if (e instanceof ApiError && e.status === 401)
        setState({ status: 'anonymous', session: null, error: '' })
      else
        setState({
          status: 'unavailable',
          session: null,
          error: e instanceof Error ? e.message : '服务暂时不可用',
        })
    }
  }, [])
  useEffect(() => {
    setUnauthorized(() => clear('管理会话已失效，请重新登录。'))
    void load()
    return () => setUnauthorized(undefined)
  }, [clear, load])
  return (
    <Context.Provider value={{ state, load, clear }}>
      {children}
    </Context.Provider>
  )
}
export const useSession = () => useContext(Context)
