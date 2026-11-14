/**
 * Audio/video layer during a show: DOM players stacked over video/audio nodes.
 * In the editor media only has poster frames; a show must be able to play, or decks
 * with video are crippled. Playback is driven two ways, like PowerPoint:
 * - media animations (Play / Pause / Stop in the click sequence) arrive as `commands`
 *   from the animation player and are applied in order as the cursor reaches them;
 * - a click on the media itself toggles play/pause ("When Clicked On").
 * Everything stops when the page turns (the layer remounts per slide).
 */
import React, { useEffect, useRef, useState } from 'react'
import type { PictureRenderNode, RenderSlide } from '@genoffice/pptx-render'
import type { SlideMediaSource } from '../../../slides-media'
import type { MediaCommand } from './animation-play'

export function ShowMediaLayer({
  slide,
  sources,
  width,
  commands,
  epoch,
  mediaBase,
  muted = false,
  interactive = true,
  hiddenIds,
}: {
  slide: RenderSlide
  sources: readonly SlideMediaSource[]
  width: number
  commands: MediaCommand[]
  /** Player load/seek generation: the applied cursor is re-based on mediaBase when it changes */
  epoch: number
  /** Commands the player's load/seek already counts as fired (see AnimPlayer.mediaBase) */
  mediaBase: number
  /** Presenter's own preview: plays in sync but silent (the audience window carries the sound) */
  muted?: boolean
  /** false = clicks fall through (presenter stage keeps its ink tools) */
  interactive?: boolean
  /** Media that play without anything on screen (a recorded narration) */
  hiddenIds?: ReadonlySet<string>
}) {
  const k = width / slide.widthPx
  const nodes = slide.nodes.filter(
    (n): n is PictureRenderNode => n.type === 'picture' && !!(n as PictureRenderNode).media,
  )
  const urls = Object.fromEntries(sources.map(source => [source.sourceId, source]))
  const [playing, setPlaying] = useState<Record<string, boolean>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const els = useRef(new Map<string, HTMLMediaElement>())
  const alive = useRef(true)
  const failed = (id: string) => { if (alive.current) setErrors(p => ({...p, [id]: '浏览器无法播放此媒体容器或编码；原始字节保留，可下载后在 PowerPoint 中播放。'})) }
  useEffect(() => { alive.current = true; return () => {
    alive.current = false
    for (const el of els.current.values()) { el.pause(); el.removeAttribute('src'); el.load() }
    els.current.clear()
  } }, [])

  // Apply the commands not seen yet, in order; a command whose element has not mounted
  // (media bytes still loading) blocks the tail until the URL arrives. A load/seek re-bases
  // the cursor on what the player counts as already fired (never below it, so a page landed
  // on in its played state stays silent; never above what was applied, so the audience's
  // per-cursor seeks keep firing the steps reached since). Callers key the layer per slide.
  const applied = useRef(0)
  const seenEpoch = useRef<number | null>(null)
  useEffect(() => {
    if (seenEpoch.current !== epoch) {
      seenEpoch.current = epoch
      applied.current = Math.max(Math.min(applied.current, commands.length), mediaBase)
    }
    while (applied.current < commands.length) {
      const c = commands[applied.current]!
      const el = els.current.get(c.sourceId)
      if (!el) {
        if (!nodes.some((n) => n.sourceId === c.sourceId) || !urls[c.sourceId]?.dataUrl) {
          applied.current++
          continue
        }
        return
      }
      runMediaCommand(el, c.effect, () => failed(c.sourceId))
      applied.current++
    }
  }, [commands, epoch, mediaBase, urls, nodes])

  const toggle = (el: HTMLMediaElement | null) => {
    if (!el) return
    if (el.paused) void el.play().catch(() => failed([...els.current].find(([, value]) => value === el)?.[0] ?? ''))
    else el.pause()
  }
  const refs = useRef(new Map<string, (el: HTMLMediaElement | null) => void>())
  const ref = (id: string) => {
    let callback = refs.current.get(id)
    if (!callback) {
      callback = el => {
        if (el) els.current.set(id, el)
        else { const previous = els.current.get(id); if (previous) { previous.pause(); previous.removeAttribute('src'); previous.load() }; els.current.delete(id) }
      }
      refs.current.set(id, callback)
    }
    return callback
  }
  return (
    <>
      {nodes.map((n) => {
        const media = urls[n.sourceId]
        if (!media?.dataUrl) return media?.reason ? <span key={n.sourceId} role="status" style={{position:'absolute',left:n.box.x*k,top:n.box.y*k,background:'#fff',color:'#222',maxWidth:n.box.w*k}}>{media.reason}</span> : null
        const style: React.CSSProperties = {
          position: 'absolute',
          left: n.box.x * k,
          top: n.box.y * k,
          width: n.box.w * k,
          height: n.box.h * k,
          cursor: interactive ? 'pointer' : undefined,
          pointerEvents: interactive ? undefined : 'none',
        }
        const isPlaying = !!playing[n.sourceId]
        const onPlay = () => {if(alive.current)setPlaying((p) => ({ ...p, [n.sourceId]: true }))}
        const onPause = () => {if(alive.current)setPlaying((p) => ({ ...p, [n.sourceId]: false }))}
        if (media.kind === 'video') {
          return (
            <React.Fragment key={n.sourceId}><video
              key={n.sourceId}
              ref={ref(n.sourceId)}
              src={media.dataUrl}
              style={style}
              aria-label="放映视频"
              data-media-id={n.sourceId}
              tabIndex={interactive?0:-1}
              onKeyDown={e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();e.stopPropagation();toggle(e.currentTarget)}}}
              onError={() => failed(n.sourceId)}
              onEnded={onPause}
              title={errors[n.sourceId] ?? media.warning}
              playsInline
              muted={muted}
              onClick={(e) => {
                e.stopPropagation()
                toggle(e.currentTarget)
              }}
              onPlay={onPlay}
              onPause={onPause}
            />{(errors[n.sourceId] || media.warning) && <span role="status" style={{position:'absolute',left:n.box.x*k,top:(n.box.y+n.box.h)*k,background:'#fff',color:'#222',maxWidth:n.box.w*k}}>{errors[n.sourceId] || media.warning}</span>}</React.Fragment>
          )
        }
        if (hiddenIds?.has(n.sourceId)) {
          return (
            <audio
              key={n.sourceId}
              ref={ref(n.sourceId)}
              src={media.dataUrl}
              data-media-id={n.sourceId}
              onError={() => failed(n.sourceId)}
              onEnded={onPause}
              muted={muted}
              onPlay={onPlay}
              onPause={onPause}
            />
          )
        }
        // Audio: the poster frame is drawn by the canvas; overlay a transparent click layer + play badge
        return (
          <div
            key={n.sourceId}
            style={{ ...style, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            data-media-control="audio" role="button" tabIndex={interactive ? 0 : -1} aria-label={isPlaying ? '暂停音频' : '播放音频'}
            onKeyDown={e => { if (['Enter',' '].includes(e.key)) { e.preventDefault(); e.stopPropagation(); toggle(els.current.get(n.sourceId) ?? null) } }}
            onClick={(e) => {
              e.stopPropagation()
              toggle(els.current.get(n.sourceId) ?? null)
            }}
          >
            <audio
              ref={ref(n.sourceId)}
              src={media.dataUrl}
              data-media-id={n.sourceId}
              onError={() => failed(n.sourceId)}
              onEnded={onPause}
              muted={muted}
              onPlay={onPlay}
              onPause={onPause}
            />
            <span
              style={{
                fontSize: Math.min(n.box.w, n.box.h) * k * 0.4,
                lineHeight: 1,
                opacity: 0.85,
              }}
            >
              {errors[n.sourceId] ? '播放失败' : isPlaying ? '\u23F8' : '\u25B6'}
            </span>
          </div>
        )
      })}
    </>
  )
}

/** OOXML media call semantics: playFrom(0.0) restarts, togglePause flips, stop rewinds. */
export function runMediaCommand(el: HTMLMediaElement, effect: MediaCommand['effect'], onError: () => void = () => {}): void {
  switch (effect) {
    case 'mediaPlay':
      el.currentTime = 0
      void el.play().catch(onError)
      break
    case 'mediaPause':
      if (el.paused) void el.play().catch(onError)
      else el.pause()
      break
    case 'mediaStop':
      el.pause()
      el.currentTime = 0
      break
  }
}
