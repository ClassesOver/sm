import React from 'react'
import * as ReactJSXRuntime from 'react/jsx-runtime'
import { createRoot, type Root } from 'react-dom/client'
import { AguiChatApp } from './components/AguiChatApp'
import { ChatRuntime } from './runtime/ChatRuntime'
import { AGUI_ODOO_PROTOCOL } from './types'
import type { AguiChatApi, AguiChatProps, MountHandle } from './types'
import './styles.css'

const VERSION = '12.0.8.8.1'

declare global {
  interface Window {
    AguiChat?: AguiChatApi
    AguiChatReact?: typeof React
    AguiChatReactJSXRuntime?: typeof ReactJSXRuntime
  }
}

function mount(el: Element, props: AguiChatProps): MountHandle {
  const root: Root = createRoot(el)
  const runtime = new ChatRuntime(props)
  let currentProps = props

  const render = () => {
    root.render(
      <React.StrictMode>
        <AguiChatApp runtime={runtime} props={currentProps} />
      </React.StrictMode>
    )
  }

  render()

  const handle: MountHandle = {
    update(nextProps: Partial<AguiChatProps> = {}) {
      currentProps = { ...currentProps, ...nextProps }
      runtime.update(nextProps)
      render()
    },
    unmount() {
      runtime.unmount()
      root.unmount()
    }
  }

  if (props.__debug) {
    handle.__runtime = runtime
  }

  return handle
}

export const AguiChat: AguiChatApi = {
  mount,
  version: VERSION,
  protocol: AGUI_ODOO_PROTOCOL
}

if (typeof window !== 'undefined') {
  window.AguiChat = AguiChat
  window.AguiChatReact = React
  window.AguiChatReactJSXRuntime = ReactJSXRuntime
}

export { ChatRuntime }
export type {
  AguiChatProps, AguiClientTool, AssistantMessageProps, ChatComponents, ChatFeedback,
  ChatIcons, ChatInteractionEvent, ChatLabels, ErrorMessageProps, MountHandle,
  HostBridge, MentionCandidate, MentionReference, MentionSearchRequest,
  MenuCatalogEntry, MenuCatalogSnapshot, OdooHostSnapshot, ProtocolHandshake,
  UserMessageProps, WorkspaceReference
} from './types'
