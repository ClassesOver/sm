import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  FILE_VIEWER_LOAD_TIMEOUT_MS,
  FILE_VIEWER_SCRIPT_URL,
  loadProductionFileViewerBundle,
  type FileViewerComponent
} from './fileViewerLoader'

const Viewer = (() => null) as unknown as FileViewerComponent

afterEach(() => {
  delete window.AguiFileViewerBundle
  document.querySelectorAll(`script[src="${FILE_VIEWER_SCRIPT_URL}"]`).forEach((script) => script.remove())
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('文件查看器加载器', () => {
  it('直接复用已注册的生产模块', async () => {
    window.AguiFileViewerBundle = { FileViewer: Viewer }

    await expect(loadProductionFileViewerBundle()).resolves.toEqual({ FileViewer: Viewer })
    expect(document.querySelector(`script[src="${FILE_VIEWER_SCRIPT_URL}"]`)).toBeNull()
  })

  it('加载生产脚本并在完成后清理事件监听', async () => {
    const promise = loadProductionFileViewerBundle()
    const script = document.querySelector<HTMLScriptElement>(`script[src="${FILE_VIEWER_SCRIPT_URL}"]`)!
    const removeEventListener = vi.spyOn(script, 'removeEventListener')
    window.AguiFileViewerBundle = { FileViewer: Viewer }
    script.dispatchEvent(new Event('load'))

    await expect(promise).resolves.toEqual({ FileViewer: Viewer })
    expect(removeEventListener).toHaveBeenCalledWith('load', expect.any(Function))
    expect(removeEventListener).toHaveBeenCalledWith('error', expect.any(Function))
  })

  it('脚本失败后移除旧节点并允许重新加载', async () => {
    const firstPromise = loadProductionFileViewerBundle()
    const firstScript = document.querySelector<HTMLScriptElement>(`script[src="${FILE_VIEWER_SCRIPT_URL}"]`)!
    firstScript.dispatchEvent(new Event('error'))
    await expect(firstPromise).rejects.toThrow('无法加载文件查看器资源')

    const secondPromise = loadProductionFileViewerBundle()
    const secondScript = document.querySelector<HTMLScriptElement>(`script[src="${FILE_VIEWER_SCRIPT_URL}"]`)!
    expect(secondScript).not.toBe(firstScript)
    window.AguiFileViewerBundle = { FileViewer: Viewer }
    secondScript.dispatchEvent(new Event('load'))
    await expect(secondPromise).resolves.toEqual({ FileViewer: Viewer })
  })

  it('资源长期无响应时结束等待并进入失败状态', async () => {
    vi.useFakeTimers()
    const promise = loadProductionFileViewerBundle()
    const rejection = expect(promise).rejects.toThrow('加载文件查看器资源超时')

    await vi.advanceTimersByTimeAsync(FILE_VIEWER_LOAD_TIMEOUT_MS)
    await rejection
  })
})
