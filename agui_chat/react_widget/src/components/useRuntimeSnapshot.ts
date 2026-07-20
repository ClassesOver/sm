import { useEffect, useRef, useState } from 'react'
import type { RuntimeSnapshot } from '../types'
import type { ChatRuntime } from '../runtime/ChatRuntime'

export function useRuntimeSnapshot(runtime: ChatRuntime): RuntimeSnapshot {
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot>(() => runtime.getSnapshot())
  const activeRuntime = useRef(runtime)

  useEffect(() => {
    const runtimeChanged = activeRuntime.current !== runtime
    activeRuntime.current = runtime
    const unsubscribe = runtime.subscribe(() => setSnapshot(runtime.getSnapshot()))
    if (runtimeChanged) setSnapshot(runtime.getSnapshot())
    return unsubscribe
  }, [runtime])

  return snapshot
}
