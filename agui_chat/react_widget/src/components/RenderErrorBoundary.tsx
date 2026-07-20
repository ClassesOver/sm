import { Component, type ReactNode } from 'react'

const EMPTY_RESET_KEYS: readonly unknown[] = []

interface RenderErrorBoundaryProps {
  children: ReactNode
  fallback: ReactNode
  resetKeys?: readonly unknown[]
}

interface RenderErrorBoundaryState {
  failed: boolean
  resetKeys: readonly unknown[]
}

function resetKeysChanged(previous: readonly unknown[], next: readonly unknown[]): boolean {
  return previous.length !== next.length || previous.some((value, index) => !Object.is(value, next[index]))
}

export class RenderErrorBoundary extends Component<RenderErrorBoundaryProps, RenderErrorBoundaryState> {
  state: RenderErrorBoundaryState = {
    failed: false,
    resetKeys: this.props.resetKeys || EMPTY_RESET_KEYS
  }

  static getDerivedStateFromProps(
    props: RenderErrorBoundaryProps,
    state: RenderErrorBoundaryState
  ): Partial<RenderErrorBoundaryState> | null {
    const resetKeys = props.resetKeys || EMPTY_RESET_KEYS
    return resetKeysChanged(state.resetKeys, resetKeys)
      ? { failed: false, resetKeys }
      : null
  }

  static getDerivedStateFromError(): Partial<RenderErrorBoundaryState> {
    return { failed: true }
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}
