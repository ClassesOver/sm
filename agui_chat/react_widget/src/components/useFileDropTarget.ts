import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'

interface UseFileDropTargetOptions {
  enabled: boolean
  disabled: boolean
  anchorRef: RefObject<HTMLElement>
  onFiles: (files: File[]) => void
}

export function filesFromDataTransfer(transfer: DataTransfer | null): File[] {
  if (!transfer) return []
  const files = Array.from(transfer.files || [])
  Array.from(transfer.items || []).forEach((item) => {
    if (item.kind !== 'file') return
    const file = item.getAsFile()
    if (file && !files.includes(file)) files.push(file)
  })
  return files
}

function hasFiles(transfer: DataTransfer | null): boolean {
  return Boolean(transfer && (
    transfer.files.length ||
    Array.from(transfer.types || []).some((type) => String(type).toLocaleLowerCase() === 'files') ||
    Array.from(transfer.items || []).some((item) => item.kind === 'file')
  ))
}

export function useFileDropTarget({
  enabled, disabled, anchorRef, onFiles
}: UseFileDropTargetOptions) {
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)
  const onFilesRef = useRef(onFiles)
  onFilesRef.current = onFiles

  useEffect(() => {
    if (!enabled || disabled) {
      dragDepth.current = 0
      setDragging(false)
      return
    }
    const dropRegion = anchorRef.current?.closest('main')
    if (!dropRegion) return
    const dragEnter = (rawEvent: Event) => {
      const event = rawEvent as globalThis.DragEvent
      if (!hasFiles(event.dataTransfer)) return
      event.preventDefault()
      dragDepth.current += 1
      setDragging(true)
    }
    const dragOver = (rawEvent: Event) => {
      const event = rawEvent as globalThis.DragEvent
      if (hasFiles(event.dataTransfer)) event.preventDefault()
    }
    const dragLeave = (rawEvent: Event) => {
      const event = rawEvent as globalThis.DragEvent
      if (dragDepth.current === 0) return
      event.preventDefault()
      dragDepth.current = Math.max(0, dragDepth.current - 1)
      if (dragDepth.current === 0) setDragging(false)
    }
    const drop = (rawEvent: Event) => {
      const event = rawEvent as globalThis.DragEvent
      const files = filesFromDataTransfer(event.dataTransfer)
      dragDepth.current = 0
      setDragging(false)
      if (!files.length) return
      event.preventDefault()
      onFilesRef.current(files)
    }
    dropRegion.addEventListener('dragenter', dragEnter)
    dropRegion.addEventListener('dragover', dragOver)
    dropRegion.addEventListener('dragleave', dragLeave)
    dropRegion.addEventListener('drop', drop)
    return () => {
      dragDepth.current = 0
      dropRegion.removeEventListener('dragenter', dragEnter)
      dropRegion.removeEventListener('dragover', dragOver)
      dropRegion.removeEventListener('dragleave', dragLeave)
      dropRegion.removeEventListener('drop', drop)
    }
  }, [anchorRef, disabled, enabled])

  return { dragging }
}
