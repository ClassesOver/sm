import { useEffect } from 'react'
import { Modal } from 'antd'
import { useBlocker } from 'react-router-dom'
export function UnsavedChangesGuard({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(dirty)
  useEffect(() => {
    if (!dirty) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])
  return (
    <Modal rootClassName="management-overlay"
      open={blocker.state === 'blocked'}
      title="放弃未保存的修改？"
      okText="放弃修改"
      cancelText="继续编辑"
      onOk={() => blocker.state === 'blocked' && blocker.proceed()}
      onCancel={() => blocker.state === 'blocked' && blocker.reset()}
    >
      <p>离开后，尚未保存的输入将被清除。</p>
    </Modal>
  )
}
