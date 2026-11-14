/**
 * Slide show — the full-screen playback view.
 *
 * - A black show layer covering the whole window, attempting system full screen (restored on exit)
 * - The playback sequence skips hidden slides (starting from a hidden slide still plays it)
 * - Moving forward plays the target page's transition effect (CSS approximations of fade/push/wipe/split/circle/random)
 * - In-page shape animations (Animations tab): moving forward plays animations step by step, turning the page only when done;
 *   going back/jumping shows the all-animations-finished state
 * - →/space/enter/PgDn/click next step/page; ←/PgUp previous page; Home/End first/last page;
 *   B/. black screen, W/, white screen (any key or click restores); digits + Enter jump to that
 *   slide number; Esc exits; advancing past the last page shows the "end of show" black screen
 * - Right-click opens PowerPoint's show menu (next/previous/last viewed/see all slides/screen/end)
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { RenderNode, RenderSlide, ShapeRenderNode } from '@genoffice/pptx-render'
import type { AnimationItem } from '../animation-types'
import type { LinkTargetOp, ShapeKey, TransitionKind } from './show-types'
import { AnimatedSlideStage, useAnimPlayer } from './AnimatedSlide'
import { t } from './show-locale'
import { MorphStage } from './MorphStage'
import { ContextMenu } from './ContextMenu'
import { SlideThumb } from './SlideThumb'
import {
  gotoPosition,
  INITIAL_SHOW_KEYS,
  pushVisited,
  reduceShowKey,
  toggleScreen,
  type ShowKeyState,
  type ShowScreen,
} from './show-keys'
import { buildShowMenu } from './show-menu'
import { computePlayOrder } from './slideshow-utils'
import { ShowMediaLayer } from './ShowMediaLayer'
import type { SlideMediaSource } from '../../../slides-media'
import { installFocusTrap } from '../../../focus-trap'

const ANIMATED = [
  'fade',
  'push',
  'wipe',
  'split',
  'circle',
  'cover',
  'pull',
  'dissolve',
  'zoom',
] as const

const GRID_THUMB_W = 200

export interface ShowViewState { pos: number; slideIndex: number; count: number; ended: boolean; pending: boolean; grid: boolean }

/** Pinned show core; desktop IPC/fullscreen/media/recording are supplied or bounded by the native host. */
export function SlideShowView({ slides, images, startAt, onExit, customOrder, animations = [], transitions = [], shapeKeys = [], links = [], viewport, onState, mediaSources = [] }: {
  slides: RenderSlide[]; images: Map<string, HTMLImageElement>; startAt: number; onExit(lastIndex: number): void; customOrder?: number[];
  animations: AnimationItem[][]; transitions: TransitionKind[]; shapeKeys: ShapeKey[][];
  links: Array<Array<{ sourceId: string; target: LinkTargetOp }>>;
  mediaSources?: readonly (readonly SlideMediaSource[])[];
  viewport: { w: number; h: number }; onState?(state: ShowViewState): void;
}) {
  // Playback sequence (original indexes): hidden pages skipped (except the start page); custom shows use the given order
  const order = useMemo(
    () => computePlayOrder(slides, startAt, customOrder),
    [slides, startAt, customOrder],
  )
  const [pos, setPos] = useState(() => Math.max(0, order.indexOf(startAt)))
  const [ended, setEnded] = useState(false)
  /** Current transition animation: kind + replay nonce (key change re-triggers the CSS animation) */
  const [anim, setAnim] = useState<{ kind: TransitionKind; nonce: number }>({
    kind: 'none',
    nonce: 0,
  })
  const size = viewport, covered = true
  const transRef = useRef(transitions)
  const allAnims = animations
  const keysRef = useRef(shapeKeys)
  const linksRef = useRef(links.map(list => new Map(list.map(({ sourceId, target }) => [sourceId, target]))))
  // Native inspect does not expose authorized run-level link metadata.
  const runLinksRef = useRef<Array<Map<string, LinkTargetOp>>>([])
  /** Morph tween in progress: previous/target page original indexes + replay nonce */
  const [morph, setMorph] = useState<{ fromIdx: number; toIdx: number; nonce: number } | null>(null)
  /** How the current page was entered: forward = initial state playing step by step, others = all-finished state */
  const navModeRef = useRef<'fresh' | 'all'>('fresh')
  /** Key state (blackout + typed digits); the screen part mirrored into state for rendering */
  const showKeysRef = useRef<ShowKeyState>(INITIAL_SHOW_KEYS)
  const [blank, setBlank] = useState<ShowScreen>('none')
  const setKeys = useCallback((k: ShowKeyState) => {
    showKeysRef.current = k
    setBlank(k.screen)
  }, [])
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const menuRef = useRef(menu)
  menuRef.current = menu
  const [grid, setGrid] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null), gridHostRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!grid) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const release = installFocusTrap(gridHostRef.current!)
    const current = gridHostRef.current?.querySelector<HTMLButtonElement>('.ss-grid-cur')
      ?? gridHostRef.current?.querySelector<HTMLButtonElement>('.ss-grid-item')
    current?.focus({ preventScroll: true })
    return () => { release(); if (previous?.isConnected) previous.focus({ preventScroll: true }); else rootRef.current?.focus({ preventScroll: true }) }
  }, [grid])
  const gridRef = useRef(grid)
  gridRef.current = grid
  /** Left button went down outside the open menu: that click only closes the menu, it must not advance */
  const menuClickRef = useRef(false)

  const slide = slides[order[pos]!]
  const player = useAnimPlayer(slide?.heightPx ?? 540, slide?.widthPx ?? 960)
  const shownSlide = slide
  useEffect(() => { onState?.({ pos, slideIndex: order[pos] ?? startAt, count: order.length, ended, pending: player.pending, grid }) }, [pos, order, startAt, ended, player.pending, grid, onState])

  // Load the page's animations when the page changes/prefetch completes (forward = initial state, back/jump = finished state)
  useEffect(() => {
    player.load(allAnims?.[order[pos]!] ?? [], navModeRef.current)
  }, [allAnims, pos, order, player.load]) // eslint-disable-line react-hooks/exhaustive-deps

  const exitRef = useRef(() => {})
  exitRef.current = () => onExit(order[Math.min(pos, order.length - 1)] ?? startAt)

  /** Play-order positions left behind by navigation ("Last Viewed" walks it back) */
  const visitedRef = useRef<number[]>([])
  const goTo = useCallback(
    (nextPos: number, animate: boolean, fromHistory = false) => {
      const target = order[nextPos]
      if (target == null) return
      if (nextPos !== pos && !fromHistory) visitedRef.current = pushVisited(visitedRef.current, pos)
      navModeRef.current = animate ? 'fresh' : 'all'
      const current = order[pos]
      let kind: TransitionKind = 'none'
      if (animate) {
        kind = transRef.current[target] ?? 'none'
        if (kind === 'random') kind = ANIMATED[Math.floor(Math.random() * ANIMATED.length)]!
      }
      if (kind === 'morph' && current != null && current !== target) {
        // Morph: skips the CSS page transition; MorphStage tweens elements from the previous page to the target
        setMorph((m) => ({ fromIdx: current, toIdx: target, nonce: (m?.nonce ?? 0) + 1 }))
        setAnim((a) => ({ kind: 'none', nonce: a.nonce + 1 }))
      } else {
        // Morphs that can't tween (start page/same page) degrade to fade-in
        if (kind === 'morph') kind = 'fade'
        setMorph(null)
        setAnim((a) => ({ kind, nonce: a.nonce + 1 }))
      }
      setPos(nextPos)
    },
    [order, pos],
  )

  const lastViewed = useCallback(() => {
    const p = visitedRef.current.pop()
    if (p == null) return
    setEnded(false)
    goTo(p, false, true)
  }, [goTo])

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

  // Element hyperlinks during the show (PowerPoint behavior): a click on a linked element follows
  // the link instead of advancing — slide links (Zoom/jump) go to that page, URLs open in the browser
  const followLink = useCallback(
    (target: LinkTargetOp) => {
      if (target.kind === 'slide') {
        const p = order.indexOf(target.slideIndex)
        // Hidden pages aren't in the play order; ignore jumps to them (matching the skip semantics)
        if (p >= 0) {
          setEnded(false)
          goTo(p, true)
        }
        return
      }
      if (target.kind === 'action') {
        const jump = (p: number | null) => {
          if (p == null || p < 0 || p >= order.length) return
          setEnded(false)
          goTo(p, true)
        }
        // Page moves only, like PowerPoint: no animation stepping, nothing past either end
        switch (target.action) {
          case 'nextslide':
            jump(pos + 1)
            return
          case 'previousslide':
            jump(pos - 1)
            return
          case 'firstslide':
            jump(0)
            return
          case 'lastslide':
            jump(order.length - 1)
            return
          case 'lastslideviewed':
            lastViewed()
            return
          case 'endshow':
            exitRef.current()
            return
        }
      }
      // Electron routes window.open to the system browser (setWindowOpenHandler denies in-app windows)
      window.open(target.url, '_blank', 'noreferrer')
    },
    [order, goTo, pos, lastViewed],
  )
  /** Click/hover position → slide-model px → topmost linked element's target (null = no link there) */
  const linkAt = useCallback(
    (e: React.MouseEvent<HTMLElement>): LinkTargetOp | null => {
      const cur = order[pos]
      const links = (cur != null ? linksRef.current[cur] : undefined) ?? new Map()
      const runLinks = (cur != null ? runLinksRef.current[cur] : undefined) ?? new Map()
      if ((!links.size && !runLinks.size) || !slide) return null
      const rect = e.currentTarget.getBoundingClientRect()
      const kx = slide.widthPx / rect.width
      return hitLink(
        slide.nodes,
        (e.clientX - rect.left) * kx,
        (e.clientY - rect.top) * kx,
        links,
        runLinks,
      )
    },
    [order, pos, slide],
  )

  // Keyboard navigation (capture beats the editor's generic shortcuts). The menu owns
  // Escape while open; the slide grid closes on Escape instead of ending the show.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' && e.target instanceof Element && e.target.closest('video,audio,[data-media-control]')) return
      if (e.defaultPrevented || e.isComposing || e.keyCode === 229 || e.ctrlKey || e.metaKey || e.altKey) return
      if (menuRef.current) return
      if (gridRef.current) {
        if (e.key === 'Escape') {
          e.preventDefault()
          e.stopImmediatePropagation()
          setGrid(false)
        }
        return
      }
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

  const onRootClick = (e: React.MouseEvent) => {
    if ((e.target as Element).closest('.ctx-menu, .ss-grid')) return
    if (showKeysRef.current.screen !== 'none') {
      setKeys(INITIAL_SHOW_KEYS)
      return
    }
    next()
  }

  if (!slide) return null
  const fitW = Math.round(Math.min(size.w, (size.h * slide.widthPx) / slide.heightPx))
  const menuItems = menu
    ? buildShowMenu(
        t,
        {
          pos,
          count: order.length,
          ended,
          pending: player.pending,
          hasLastViewed: visitedRef.current.length > 0,
          screen: blank,
        },
        {
          next,
          prev,
          lastViewed,
          seeAll: () => setGrid(true),
          setScreen: (sc) => {
            if (!ended) setKeys(toggleScreen(showKeysRef.current, sc))
          },
          end: () => exitRef.current(),
        },
      )
    : null

  return (
    <div
      ref={rootRef}
      tabIndex={-1}
      className="slideshow"
      onClick={onRootClick}
      onMouseDownCapture={(e) => {
        menuClickRef.current =
          menu != null && e.button === 0 && !(e.target as Element).closest('.ctx-menu')
      }}
      onClickCapture={(e) => {
        if (!menuClickRef.current) return
        menuClickRef.current = false
        e.stopPropagation()
      }}
      onContextMenu={(e) => {
        e.preventDefault()
        if (!covered || grid) return
        setMenu({ x: e.clientX, y: e.clientY })
      }}
    >
      {!covered ? null : ended ? (
        <div className="ss-end">{t('paneShowEndedClick')}</div>
      ) : (
        <>
          {morph && slides[morph.fromIdx] && slides[morph.toIdx] ? (
            <div key={`morph-${morph.nonce}`} className="ss-frame">
              <MorphStage
                from={slides[morph.fromIdx]!}
                to={slides[morph.toIdx]!}
                fromKeys={keysRef.current[morph.fromIdx] ?? []}
                toKeys={keysRef.current[morph.toIdx] ?? []}
                images={images}
                width={fitW}
                onDone={() => setMorph(null)}
              />
            </div>
          ) : (
            <div
              key={anim.nonce}
              className={`ss-frame${anim.kind !== 'none' ? ` ss-anim-${anim.kind}` : ''}`}
            >
              <div
                style={{ position: 'relative', width: fitW, margin: '0 auto' }}
                onClick={(e) => {
                  const target = linkAt(e)
                  if (!target) return // Bubbles to the root onClick → next page
                  e.stopPropagation()
                  followLink(target)
                }}
                onMouseMove={(e) => {
                  e.currentTarget.style.cursor = linkAt(e) ? 'pointer' : ''
                }}
              >
                <AnimatedSlideStage
                  slide={shownSlide!}
                  images={images}
                  width={fitW}
                  states={player.states}
                />
                <ShowMediaLayer key={order[pos]} slide={shownSlide!} sources={mediaSources[order[pos]!] ?? []} width={fitW} commands={player.mediaCmds} epoch={player.epoch} mediaBase={player.mediaBase} />
              </div>
            </div>
          )}
          <div className="ss-counter" aria-hidden="true">
            {pos + 1} / {order.length}
          </div>
          {blank !== 'none' && <div className={blank === 'black' ? 'ss-black' : 'ss-white'} />}
        </>
      )}
      {grid && (
        <div
          ref={gridHostRef}
          className="ss-grid"
          onClick={(e) => {
            e.stopPropagation()
            setGrid(false)
          }}
        >
          {order.map((idx, p) => (
            <button
              key={idx}
              className={`ss-grid-item${p === pos ? ' ss-grid-cur' : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                setGrid(false)
                setEnded(false)
                goTo(p, false)
              }}
            >
              <SlideThumb slide={slides[idx]!} images={images} width={GRID_THUMB_W} />
              <span className="ss-grid-num">{idx + 1}</span>
            </button>
          ))}
        </div>
      )}
      {menu && menuItems && (
        <ContextMenu x={menu.x} y={menu.y} items={menuItems} onClose={() => setMenu(null)} />
      )}
    </div>
  )
}

/**
 * Topmost linked element at a point (slide-model px). Scans nodes back-to-front (z-order),
 * descends into groups (children boxes are group-local); unlinked overlapping nodes don't block
 * links underneath (lenient, matches the show's forgiving click behavior).
 */
function hitLink(
  nodes: RenderNode[],
  x: number,
  y: number,
  links: Map<string, LinkTargetOp>,
  runLinks: Map<string, LinkTargetOp>,
): LinkTargetOp | null {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i]!
    const { box } = n
    if (x < box.x || y < box.y || x > box.x + box.w || y > box.y + box.h) continue
    if (n.type === 'group') {
      const inner = hitLink(n.children, x - box.x, y - box.y, links, runLinks)
      if (inner) return inner
    }
    // Run-level link on the glyph under the pointer beats the whole-element link (more specific)
    const text = (n as ShapeRenderNode).text
    if (text && runLinks.size) {
      let para = -1
      for (const ln of text.lines) {
        if (ln.paraStart !== false) para++
        const ly = box.y + text.insets.t + ln.top
        if (y < ly || y > ly + ln.height) continue
        for (const r of ln.runs) {
          if (r.srcRunIdx == null) continue
          const rx = box.x + text.insets.l + r.x
          if (x < rx || x > rx + r.widthPx) continue
          const target = runLinks.get(`${n.sourceId}:${para}:${r.srcRunIdx}`)
          if (target) return target
        }
      }
    }
    const target = links.get(n.sourceId)
    if (target) return target
  }
  return null
}
