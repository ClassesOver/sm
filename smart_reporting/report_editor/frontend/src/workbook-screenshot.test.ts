import { afterEach, expect, it, vi } from 'vitest'
import { captureWorkbookScreenshot } from './workbook-screenshot'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function media() {
  const stop = vi.fn()
  const track = Object.assign(new EventTarget(), { stop, readyState: 'live' })
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] } as unknown as MediaStream
  const getDisplayMedia = vi.fn<() => Promise<MediaStream>>().mockResolvedValue(stream)
  vi.stubGlobal('navigator', { mediaDevices: { getDisplayMedia } })
  return { getDisplayMedia, stop }
}

it('captures one full-resolution frame after browser consent and stops sharing', async () => {
  const { getDisplayMedia, stop } = media()
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLVideoElement) {
    Object.defineProperties(this, { videoWidth: { value: 1920 }, videoHeight: { value: 1080 } })
    this.dispatchEvent(new Event('loadeddata'))
    return Promise.resolve()
  })
  const drawImage = vi.fn()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D)
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockImplementation(function (this: HTMLCanvasElement) {
    expect([this.width, this.height]).toEqual([1920, 1080])
    return 'data:image/png;base64,iVBORw0KGgo='
  })
  const result = await captureWorkbookScreenshot(new AbortController().signal)
  expect(getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: false })
  expect(drawImage).toHaveBeenCalledOnce()
  expect(result).toMatchObject({ name: 'Screenshot.png', width: 480, height: 270 })
  expect(stop).toHaveBeenCalledOnce()
})

it('stops a late sharing grant after the workbook closes without capturing a frame', async () => {
  const { getDisplayMedia, stop } = media()
  let grant!: (value: MediaStream) => void
  const stream = await getDisplayMedia()
  getDisplayMedia.mockImplementation(() => new Promise(resolve => { grant = resolve }))
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play')
  const abort = new AbortController()
  const result = captureWorkbookScreenshot(abort.signal)
  abort.abort()
  grant(stream)
  await expect(result).rejects.toMatchObject({ name: 'AbortError' })
  expect(play).not.toHaveBeenCalled()
  expect(stop).toHaveBeenCalledOnce()
})

it('reports browser cancellation without creating a frame', async () => {
  const { getDisplayMedia, stop } = media()
  getDisplayMedia.mockRejectedValueOnce(new DOMException('cancelled', 'NotAllowedError'))
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play')
  await expect(captureWorkbookScreenshot(new AbortController().signal)).rejects.toThrow('未授权或已取消屏幕截图')
  expect(play).not.toHaveBeenCalled()
  expect(stop).not.toHaveBeenCalled()
})
