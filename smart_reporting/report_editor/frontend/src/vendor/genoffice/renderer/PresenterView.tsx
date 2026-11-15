/** GenOffice browser presenter view, driven by the authorized slide snapshot. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { RenderSlide } from '@genoffice/pptx-render'
import type { AnimationItem } from '../animation-types'
import type { SlideMediaSource } from '../../../slides-media'
import { AnimatedSlideStage, useAnimPlayer } from './AnimatedSlide'
import { ShowMediaLayer } from './ShowMediaLayer'
import { t } from './presenter-locale'
import { SlideThumb } from './SlideThumb'
import { InkLayer, type InkStroke } from './ShowInk'
import {
  gotoPosition,
  INITIAL_SHOW_KEYS,
  reduceShowKey,
  toggleScreen,
  type ShowKeyState,
  type ShowScreen,
} from './show-keys'

/** Layout constants (aligned with styles.css) */
const SIDE_W = 340
const TOP_H = 44
const TIMER_H = 40
const BOTTOM_H = 56
const FILM_H = 118

const PEN_COLOR = '#e53935'

/** Elapsed show seconds → mm:ss (past 1 hour minutes keep accumulating) */
function fmtElapsed(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function fmtWallClock(): string {
  const d = new Date()
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function PresenterView({
  slides,
  images,
  startAt,
  onExit,
  onUseSlideShow,
  animations,
  notes: allNotes,
  mediaSources,
}: {
  slides: RenderSlide[]
  images: Map<string, HTMLImageElement>
  /** Start page (original index) */
  startAt: number
  animations: AnimationItem[][]
  notes: string[]
  mediaSources?: readonly (readonly SlideMediaSource[])[]
  /** Exit presenter view; lastIndex is the original index of the page dwelt on (for locating back in the edit view) */
  onExit: (lastIndex: number) => void
  /** "Switch to normal show": exit this view and start a normal show from lastIndex */
  onUseSlideShow?: (lastIndex: number) => void
}) {
  // Playback sequence (original indexes): hidden pages skipped; the start page kept even if hidden (consistent with SlideShowView)
  const order = useMemo(() => {
    const o = slides.map((_, i) => i).filter((i) => !slides[i]!.hidden || i === startAt)
    return o.length > 0 ? o : [startAt]
  }, [slides, startAt])
  const [pos, setPos] = useState(() => Math.max(0, order.indexOf(startAt)))
  const [ended, setEnded] = useState(false)
  /** Key state (blackout + typed digits); the screen part mirrored into state for rendering/sync */
  const showKeysRef = useRef<ShowKeyState>(INITIAL_SHOW_KEYS)
  const [blank, setBlank] = useState<ShowScreen>('none')
  const setKeys = useCallback((k: ShowKeyState) => {
    showKeysRef.current = k
    setBlank(k.screen)
  }, [])
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight })
  const navModeRef = useRef<'fresh' | 'all'>('fresh')

  // ── Timer (pausable/resettable) and clock ──────────────────────────────────
  const [elapsed, setElapsed] = useState(0)
  const [paused, setPaused] = useState(false)
  const [clock, setClock] = useState(fmtWallClock)
  useEffect(() => {
    if (paused) return
    const t = window.setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [paused])
  useEffect(() => {
    const t = window.setInterval(() => setClock(fmtWallClock()), 10_000)
    return () => window.clearInterval(t)
  }, [])

  // ── Notes font size ──────────────────────────────────────────────────
  const [noteSize, setNoteSize] = useState(15)

  // ── Ink/laser pointer ───────────────────────────────────────────────
  const [tool, setTool] = useState<'none' | 'pen' | 'laser'>('none')
  const [strokes, setStrokes] = useState<InkStroke[]>([])
  const [laser, setLaser] = useState<{ x: number; y: number } | null>(null)
  const stageboxRef = useRef<HTMLDivElement>(null)
  const drawingRef = useRef(false)
  const slide = slides[order[pos]!]
  const player = useAnimPlayer(slide?.heightPx ?? 540, slide?.widthPx ?? 960)

  useEffect(() => {
    player.load(animations[order[pos]!] ?? [], navModeRef.current)
  }, [animations, pos, order, player.load])

  useEffect(() => {
    drawingRef.current = false
    setStrokes([])
    setLaser(null)
  }, [pos])

  const exitRef = useRef(() => {})
  exitRef.current = () => onExit(order[Math.min(pos, order.length - 1)] ?? startAt)

  useEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth, h: window.innerHeight })
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const goTo = useCallback((nextPos: number, fresh: boolean) => {
    navModeRef.current = fresh ? 'fresh' : 'all'
    setPos(nextPos)
  }, [])

  const next = useCallback(() => {
    if (ended) {
      exitRef.current()
      return
    }
    // Advance in-page animations first; turn the page only when this page's animations are done
    if (player.advance()) return
    if (pos >= order.length - 1) setEnded(true)
    else goTo(pos + 1, true)
  }, [ended, pos, order.length, goTo, player.advance]) // eslint-disable-line react-hooks/exhaustive-deps

  const prev = useCallback(() => {
    if (ended) {
      setEnded(false)
      return
    }
    if (pos > 0) goTo(pos - 1, false)
  }, [ended, pos, goTo])

  // Keyboard navigation (capture beats the editor's generic shortcuts; keys match SlideShowView)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing || e.ctrlKey || e.metaKey || e.altKey ||
          ([' ', 'Enter'].includes(e.key) && e.target instanceof Element && e.target.closest('button'))) return
      const r = reduceShowKey(showKeysRef.current, e.key)
      if (!r) return
      e.preventDefault()
      e.stopImmediatePropagation()
      setKeys(ended ? { ...r.state, screen: 'none' } : r.state)
      switch (r.action.type) {
        case 'exit':
          exitRef.current()
          return
        case 'next':
          next()
          return
        case 'prev':
          prev()
          return
        case 'first':
          setEnded(false)
          goTo(0, false)
          return
        case 'last':
          setEnded(false)
          goTo(order.length - 1, false)
          return
        case 'goto': {
          const p = gotoPosition(r.action.slideNumber, order)
          if (p == null) return
          setEnded(false)
          goTo(p, false)
          return
        }
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [next, prev, goTo, order, ended, setKeys])

  // Scroll the current thumbnail into view
  const filmRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    filmRef.current
      ?.querySelector('.pv-film-cur')
      ?.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
  }, [pos])

  const clearInk = useCallback(() => {
    setStrokes([])
    setLaser(null)
  }, [])

  // ── Ink pointer events (normalized coordinates, each side restores its own) ────────────
  const normPoint = useCallback((e: React.PointerEvent): { x: number; y: number } | null => {
    const r = stageboxRef.current?.getBoundingClientRect()
    if (!r || r.width === 0 || r.height === 0) return null
    return {
      x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    }
  }, [])

  const onStagePointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (tool !== 'pen') return
      const p = normPoint(e)
      if (!p) return
      e.currentTarget.setPointerCapture(e.pointerId)
      drawingRef.current = true
      setStrokes((ss) => [...ss, { color: PEN_COLOR, points: [p.x, p.y] }])
    },
    [tool, normPoint],
  )

  const onStagePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (tool === 'pen' && drawingRef.current) {
        const p = normPoint(e)
        if (!p) return
        setStrokes((ss) => {
          const last = ss[ss.length - 1]
          if (!last) return ss
          return [...ss.slice(0, -1), { ...last, points: [...last.points, p.x, p.y] }]
        })
      } else if (tool === 'laser') {
        const p = normPoint(e)
        if (!p) return
        setLaser(p)
      }
    },
    [tool, normPoint],
  )

  const onStagePointerUp = useCallback(() => {
    drawingRef.current = false
  }, [])

  const onStagePointerLeave = useCallback(() => {
    if (tool === 'laser') {
      setLaser(null)
    }
  }, [tool])

  if (!slide) return null

  // Left main area auto-fit: subtract the right column/top bar/timer row/toolbar/thumbnail strip, then take the max fit by aspect ratio
  const ar = slide.widthPx / slide.heightPx
  const sideW = Math.min(SIDE_W, Math.floor(size.w * 0.36))
  const mainW = size.w - sideW
  const mainH = size.h - TOP_H - TIMER_H - BOTTOM_H - FILM_H
  const fitW = Math.max(80, Math.round(Math.min(mainW - 48, (mainH - 16) * ar)))
  const fitH = Math.round(fitW / ar)

  const nextSlide = ended ? null : (slides[order[pos + 1] ?? -1] ?? null)
  const notes = allNotes[order[pos]!] ?? ''

  const useShow = () => {
    onUseSlideShow?.(order[Math.min(pos, order.length - 1)] ?? startAt)
  }

  return (
    <div className="presenter">
      <div className="pv-top">
        <button
          className="pv-top-btn pv-top-exit"
          onClick={() => exitRef.current()}
          data-tip={t('panePresenterEndTip')}
        >
          ⊗ {t('panePresenterEndShow')}
        </button>
        {onUseSlideShow && (
          <button className="pv-top-btn" onClick={useShow} data-tip={t('panePresenterUseShowTip')}>
            ▤ {t('panePresenterUseShow')}
          </button>
        )}
        <div className="pv-top-spacer" />

      </div>
      <div className="pv-body">
        <div className="pv-left">
          <div className="pv-timer-row">
            <span className="pv-timer" data-tip={t('panePresenterElapsed')}>
              {fmtElapsed(elapsed)}
            </span>
            <button
              className="pv-mini-btn"
              onClick={() => setPaused((v) => !v)}
              data-tip={paused ? t('panePresenterResume') : t('panePresenterPause')}
              aria-label={paused ? t('panePresenterResume') : t('panePresenterPause')}
            >
              {paused ? '▶' : '❚❚'}
            </button>
            <button
              className="pv-mini-btn"
              onClick={() => {
                setElapsed(0)
                setPaused(false)
              }}
              data-tip={t('panePresenterRestart')}
              aria-label={t('panePresenterRestart')}
            >
              ↻
            </button>
            <div className="pv-top-spacer" />
            <span className="pv-clock" data-tip={t('panePresenterClock')}>
              {clock}
            </span>
          </div>
          <div
            className="pv-stage"
            onClick={
              tool === 'none'
                ? () => (blank === 'none' ? next() : setKeys(INITIAL_SHOW_KEYS))
                : undefined
            }
          >
            {ended ? (
              <div className="pv-end">{t('panePresenterEnded')}</div>
            ) : (
              <div
                ref={stageboxRef}
                className={`pv-stagebox${tool !== 'none' ? ` pv-tool-${tool}` : ''}`}
                style={{ width: fitW, height: fitH }}
                onPointerDown={onStagePointerDown}
                onPointerMove={onStagePointerMove}
                onPointerUp={onStagePointerUp}
                onPointerLeave={onStagePointerLeave}
              >
                <AnimatedSlideStage
                  slide={slide}
                  images={images}
                  width={fitW}
                  states={player.states}
                />
                <ShowMediaLayer
                  key={order[pos]!}
                  slide={slide}
                  sources={mediaSources?.[order[pos]!] ?? []}
                  width={fitW}
                  commands={player.mediaCmds}
                  epoch={player.epoch}
                  mediaBase={player.mediaBase}
                  muted
                  interactive={false}
                />
                <InkLayer strokes={strokes} laser={laser} width={fitW} height={fitH} />
                {blank !== 'none' && (
                  <div
                    className={blank === 'black' ? 'pv-black' : 'pv-white'}
                    data-tip={t(
                      blank === 'black' ? 'panePresenterBlackOn' : 'panePresenterWhiteOn',
                    )}
                  />
                )}
              </div>
            )}
          </div>
          <div className="pv-bottomrow">
            <div className="pv-tools">
              <button
                className={`pv-tool-btn${tool === 'pen' ? ' pv-tool-on' : ''}`}
                onClick={() => setTool((cur) => (cur === 'pen' ? 'none' : 'pen'))}
                data-tip={t('panePresenterPen')}
                aria-label={t('panePresenterPen')}
              >
                ✎
              </button>
              <button
                className={`pv-tool-btn${tool === 'laser' ? ' pv-tool-on' : ''}`}
                onClick={() => setTool((cur) => (cur === 'laser' ? 'none' : 'laser'))}
                data-tip={t('panePresenterLaser')}
                aria-label={t('panePresenterLaser')}
              >
                ◉
              </button>
              <button
                className="pv-tool-btn"
                disabled={strokes.length === 0}
                onClick={clearInk}
                data-tip={t('panePresenterEraseInk')}
                aria-label={t('panePresenterEraseInk')}
              >
                ⌫
              </button>
              <button
                className={`pv-tool-btn${blank === 'black' ? ' pv-tool-on' : ''}`}
                onClick={() => setKeys(toggleScreen(showKeysRef.current, 'black'))}
                data-tip={t('panePresenterBlackTip')}
                aria-label={t('panePresenterBlackTip')}
              >
                ▮
              </button>
            </div>
            <div className="pv-nav">
              <button
                className="pv-round"
                disabled={!ended && pos === 0}
                onClick={prev}
                data-tip={t('panePresenterPrevTip')}
                aria-label={t('panePresenterPrevTip')}
              >
                ‹
              </button>
              <div className="pv-nav-mid">
                <div className="pv-nav-label">
                  {t('panePresenterSlideOf', { cur: pos + 1, total: order.length })}
                </div>
                <div className="pv-progress">
                  <div style={{ width: `${Math.round(((pos + 1) / order.length) * 100)}%` }} />
                </div>
              </div>
              <button
                className="pv-round"
                onClick={next}
                data-tip={t('panePresenterNextTip')}
                aria-label={t('panePresenterNextTip')}
              >
                ›
              </button>
            </div>
            <div className="pv-tools" style={{ visibility: 'hidden' }} aria-hidden />
          </div>
        </div>
        <div className="pv-side" style={{ width: sideW }}>
          <div className="pv-section-label">{t('panePresenterNextSlide')}</div>
          <div className="pv-next">
            {nextSlide ? (
              <SlideThumb slide={nextSlide} images={images} width={Math.max(80, sideW - 28)} />
            ) : (
              <div className="pv-next-none">{ended ? '—' : t('panePresenterLastSlide')}</div>
            )}
          </div>
          <div className="pv-section-label">{t('panePresenterNotes')}</div>
          <div className="pv-notes" style={{ fontSize: noteSize }}>
            {notes.trim() ? notes : t('panePresenterNoNotes')}
          </div>
          <div className="pv-notes-size">
            <button
              className="pv-mini-btn"
              onClick={() => setNoteSize((s) => Math.min(28, s + 2))}
              data-tip={t('panePresenterNotesBigger')}
            >
              A⁺
            </button>
            <button
              className="pv-mini-btn"
              onClick={() => setNoteSize((s) => Math.max(11, s - 2))}
              data-tip={t('panePresenterNotesSmaller')}
            >
              A⁻
            </button>
          </div>
        </div>
      </div>
      <div className="pv-film" ref={filmRef}>
        {order.map((idx, i) => (
          <div
            key={idx}
            className={`pv-film-item${i === pos ? ' pv-film-cur' : ''}`}
            onClick={() => {
              setEnded(false)
              goTo(i, false)
            }}
            data-tip={t('panePresenterFilmSlideN', { n: i + 1 })}
          >
            <SlideThumb slide={slides[idx]!} images={images} width={150} />
          </div>
        ))}
      </div>
    </div>
  )
}
