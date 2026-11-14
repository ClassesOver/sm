/**
 * Cutout (background removal) dialog — a simplified take on PowerPoint "Remove Background".
 *
 * Entry: select a picture → format pane / "Picture Format" tab / context menu "Remove background".
 * Interaction: tolerance slider (0-100) with live preview, checkerboard background shows
 * transparent areas; on apply, calls back with the background-removed PNG dataUrl (with alpha)
 * and App replaces the original picture.
 *
 * Performance: slider preview computes on a ≤520px downsampled copy to stay smooth; clicking
 * "Apply" recomputes at the original resolution, and representative background colors are always
 * sampled from the original-resolution border.
 * Reuses SettingsModal's .modal-backdrop/.modal styles.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { removeBackground, sampleBackgroundColors, type PixelImage, type RGB } from './slides-cutout-pixels'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {installFocusTrap} from './focus-trap'
import './slides-cutout-dialog.css'


/** Longest side of the preview canvas (px) */
const PREVIEW_MAX = 520
const DEFAULT_TOLERANCE = 30

/** Checkerboard background: visualizes transparent areas */
const CHECKERBOARD: React.CSSProperties = {
  background: 'repeating-conic-gradient(#d5d5d5 0% 25%, #ffffff 0% 50%) 0 0 / 16px 16px',
}

interface Props {
  /** Original image dataUrl (full source, without crop) */
  dataUrl: string
  /** Apply: the background-removed PNG dataUrl (with alpha channel) */
  onApply: (pngDataUrl: string) => void
  onCancel: () => void
  isCurrent:()=>boolean
}

export function CutoutDialog({ dataUrl, onApply, onCancel,isCurrent }: Props) {
  const t=(key:string,values?:Record<string,number>)=>(labels[key]??key).replace(/\{(\w+)\}/g,(_,name)=>String(values?.[name]??''))
  const [tolerance, setTolerance] = useState(DEFAULT_TOLERANCE)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [applyError,setApplyError]=useState('')
  const [removedPct, setRemovedPct] = useState(0)
  const [applying, setApplying] = useState(false)

  const canvasRef = useRef<HTMLCanvasElement>(null)
  /** Original-resolution pixels (used on apply) */
  const fullRef = useRef<PixelImage | null>(null)
  /** Downsampled pixels (for live slider preview) */
  const previewRef = useRef<PixelImage | null>(null)
  /** Representative background colors (sampled from the original-resolution border; shared by preview/apply for consistency) */
  const bgColorsRef = useRef<RGB[]>([])
  const rafRef = useRef<number | null>(null)
  const applyTimer=useRef<number|undefined>(undefined)
  const alive=useRef(true)
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;if(applyTimer.current!==undefined)window.clearTimeout(applyTimer.current)}},[])

  /** Recompute the preview at the current tolerance and draw it */
  const renderPreview = useCallback((tol: number) => {
    const pv = previewRef.current
    const canvas = canvasRef.current
    if (!pv || !canvas) return
    const result = removeBackground(pv, tol, bgColorsRef.current)
    canvas.getContext('2d')!.putImageData(new ImageData(result.data, pv.width, pv.height), 0, 0)
    setRemovedPct(Math.round((result.removedCount / (pv.width * pv.height)) * 100))
  }, [])

  // Load the original → two pixel sets (original resolution + preview resolution), and draw the first preview frame
  useEffect(() => {
    let cancelled = false
    const img = new Image()
    img.onload = () => {
      if (cancelled||!isCurrent()) return
      try {
      const w = img.naturalWidth
      const h = img.naturalHeight
      if (!w || !h || w*h>100_000_000) {
        setError('paneCutoutDecodeFail')
        return
      }
      const grab = (dw: number, dh: number): PixelImage => {
        const c = document.createElement('canvas')
        c.width = dw
        c.height = dh
        const ctx = c.getContext('2d')!
        ctx.drawImage(img, 0, 0, dw, dh)
        const d = ctx.getImageData(0, 0, dw, dh)
        return { data: d.data, width: dw, height: dh }
      }
      const full = grab(w, h)
      const scale = Math.min(1, PREVIEW_MAX / Math.max(w, h))
      const preview =
        scale < 1
          ? grab(Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale)))
          : full
      fullRef.current = full
      previewRef.current = preview
      bgColorsRef.current = sampleBackgroundColors(full)
      const canvas = canvasRef.current
      if (canvas) {
        canvas.width = preview.width
        canvas.height = preview.height
      }
      setLoaded(true)
      renderPreview(DEFAULT_TOLERANCE)
      }catch{if(!cancelled)setError('paneCutoutDecodeFail')}
    }
    img.onerror = () => {
      if (!cancelled) setError('paneCutoutLoadFail')
    }
    img.src=dataUrl
    return () => {
      cancelled = true
      img.onload=null;img.onerror=null
    }
  }, [dataUrl, renderPreview,isCurrent])

  // Slider change → recompute the preview coalesced by rAF
  const onTolerance = (v: number) => {
    setTolerance(v)
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null
      renderPreview(v)
    })
  }
  useEffect(
    () => () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    },
    [],
  )

  /** Apply: recompute at original resolution → PNG dataUrl with alpha */
  const apply = () => {
    const full = fullRef.current
    if (!full || applying) return
    setApplyError('')
    setApplying(true)
    // Let "Processing…" render first, then do the recomputation
    applyTimer.current=window.setTimeout(() => {
      if(!alive.current)return
      try {
        if(!isCurrent())throw Error('页面、选择或草稿已变化，请取消后重新打开')
        const result = removeBackground(full, tolerance, bgColorsRef.current)
        const c = document.createElement('canvas')
        c.width = full.width
        c.height = full.height
        c.getContext('2d')!.putImageData(new ImageData(result.data, full.width, full.height), 0, 0)
        onApply(c.toDataURL('image/png'))
      } catch(cause) {
        if(!alive.current)return
        setApplying(false)
        setApplyError(cause instanceof Error?cause.message:t('paneCutoutApplyFail'))
      }
    }, 30)
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div
        className="modal"
        style={{ maxWidth: PREVIEW_MAX + 48 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2>{t('paneCutoutTitle')}</h2>
        <div
          className="cutout-preview"
          style={{
            ...CHECKERBOARD,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: 160,
            maxHeight: PREVIEW_MAX,
            borderRadius: 4,
            overflow: 'hidden',
          }}
        >
          {error ? (
            <span role="alert"
              style={{
                color: 'var(--danger)',
                background: 'var(--surface)',
                padding: '4px 10px',
                borderRadius: 4,
              }}
            >
              {t(error)}
            </span>
          ) : (
            <canvas
              ref={canvasRef}
              style={{
                maxWidth: '100%',
                maxHeight: PREVIEW_MAX,
                display: loaded ? 'block' : 'none',
              }}
            />
          )}
          {!loaded && !error && (
            <span style={{ color: 'var(--text-secondary)' }}>{t('paneCutoutLoading')}</span>
          )}
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
          <span style={{ whiteSpace: 'nowrap' }}>{t('paneCutoutTolerance')}</span>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={tolerance}
            disabled={!loaded || applying}
            onChange={(e) => onTolerance(Number(e.target.value))}
            style={{ flex: 1 }}
          />
          <span style={{ width: 32, textAlign: 'right' }}>{tolerance}</span>
        </label>
        <div data-cutout-hint style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
          {t('paneCutoutHint', { pct: removedPct })}
        </div>
        {applyError&&<p role="alert">{applyError}</p>}
        <div className="modal-actions">
          <button onClick={onCancel} disabled={applying}>
            {t('paneCancel')}
          </button>
          <button className="primary" onClick={apply} disabled={!loaded || !!error || applying}>
            {applying ? t('paneCutoutApplying') : t('paneCutoutApply')}
          </button>
        </div>
      </div>
    </div>
  )
}

const labels:Record<string,string>={paneCutoutTitle:'去除背景',paneCutoutDecodeFail:'图片解码失败',paneCutoutLoadFail:'图片加载失败',paneCutoutApplyFail:'去背景处理失败',paneCutoutLoading:'加载中…',paneCutoutTolerance:'容差',paneCutoutHint:'自动从图片边缘采样背景色；容差越大，去除的相近颜色越多。当前预览已移除约 {pct}% 像素。',paneCutoutApplying:'处理中…',paneCutoutApply:'应用',paneCancel:'取消'}
export function openSlidesCutout(host:HTMLElement,options:{dataUrl:string;isCurrent:()=>boolean;onApply:(dataUrl:string)=>void}){
 const opener=document.activeElement instanceof HTMLElement?document.activeElement:undefined,element=document.createElement('dialog');element.className='slides-cutout-dialog';element.setAttribute('aria-label','去除背景');host.append(element)
 const root=createRoot(element),release=installFocusTrap(element);let disposed=false
 const dispose=()=>{if(disposed)return;disposed=true;release();flushSync(()=>root.unmount());element.remove();if(opener?.isConnected)opener.focus({preventScroll:true})}
 element.addEventListener('cancel',event=>{event.preventDefault();dispose()});element.addEventListener('keydown',event=>{if(event.isComposing||event.keyCode===229||event.defaultPrevented)return;if(event.key==='Escape'){event.preventDefault();dispose()}event.stopPropagation()})
 flushSync(()=>root.render(<CutoutDialog dataUrl={options.dataUrl} isCurrent={options.isCurrent} onCancel={dispose} onApply={dataUrl=>{if(disposed||!options.isCurrent())throw Error('页面、选择或草稿已变化，请取消后重新打开');options.onApply(dataUrl);dispose()}}/>));element.showModal?.();element.querySelector<HTMLElement>('button')?.focus({preventScroll:true});return {element,dispose}
}
