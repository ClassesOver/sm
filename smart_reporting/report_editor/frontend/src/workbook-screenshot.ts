import type { PictureInput } from './workbook-pictures'

const pngPrefix = 'data:image/png;base64,'
const maximumBase64Length = 8 * 1024 * 1024

export function supportsWorkbookScreenshot() {
  return typeof navigator.mediaDevices?.getDisplayMedia === 'function'
}

function waitForFrame(video: HTMLVideoElement, track: MediaStreamTrack, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(failed, 10_000)
    const cleanup = () => {
      clearTimeout(timeout)
      video.removeEventListener('loadeddata', ready)
      video.removeEventListener('error', failed)
      track.removeEventListener('ended', failed)
      signal.removeEventListener('abort', aborted)
    }
    function ready() { cleanup(); resolve() }
    function failed() { cleanup(); reject(new Error('未能读取屏幕画面，请重新截图')) }
    function aborted() { cleanup(); reject(signal.reason) }
    if (signal.aborted) { aborted(); return }
    if (track.readyState === 'ended') { failed(); return }
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) { ready(); return }
    video.addEventListener('loadeddata', ready)
    video.addEventListener('error', failed)
    track.addEventListener('ended', failed)
    signal.addEventListener('abort', aborted)
    void video.play().catch(failed)
  })
}

/** Web host for GenOffice Insert → Screenshot: user-selected surface → one PNG frame. */
export async function captureWorkbookScreenshot(signal: AbortSignal): Promise<PictureInput> {
  signal.throwIfAborted()
  if (!supportsWorkbookScreenshot()) throw new Error('当前浏览器不支持屏幕截图')
  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false })
  } catch {
    signal.throwIfAborted()
    throw new Error('未授权或已取消屏幕截图')
  }
  const video = document.createElement('video')
  const tracks = stream.getTracks()
  try {
    signal.throwIfAborted()
    const track = stream.getVideoTracks()[0]
    if (!track) throw new Error('没有可用的屏幕画面')
    video.muted = true
    video.playsInline = true
    video.srcObject = stream
    await waitForFrame(video, track, signal)
    signal.throwIfAborted()
    const { videoWidth: width, videoHeight: height } = video
    if (!width || !height || width > 30_000 || height > 30_000 || width * height > 33_554_432) {
      throw new Error('截图尺寸超出范围，请选择较小的捕获区域')
    }
    const canvas = document.createElement('canvas')
    canvas.width = width; canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('无法准备截图画布')
    context.drawImage(video, 0, 0)
    const dataUrl = canvas.toDataURL('image/png')
    if (!dataUrl.startsWith(pngPrefix) || dataUrl.length <= pngPrefix.length) throw new Error('无法生成 PNG 截图')
    if (dataUrl.length > pngPrefix.length + maximumBase64Length) throw new Error('截图须在 6 MiB 以内')
    const scale = Math.min(1, 480 / width, 320 / height)
    return { dataUrl, width: width * scale, height: height * scale, name: 'Screenshot.png' }
  } finally {
    for (const track of tracks) track.stop()
    video.srcObject = null
  }
}
