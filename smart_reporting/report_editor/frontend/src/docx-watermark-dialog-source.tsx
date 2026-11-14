/**
 * Word's Insert Watermark dialog: No watermark / Picture (scale, washout) /
 * Text (face, size, bold, italic, transparency, color, layout), with a page
 * preview drawn through the same helpers the page preview and save use.
 */
import { useEffect, useRef, useState } from 'react'
import {
  pictureWatermarkPreviewImage,
  textWatermarkPreviewImage,
  type HfImage,
  type PictureWatermarkSpec,
  type Watermark,
  type WatermarkSpec,
} from '@genoffice/docx-engine'
import { useI18n } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/locale'
import { fontFamiliesFor } from './vendor/genoffice-docs/apps/docs/src/renderer/font-list'
import { hfWashoutFilter, wordArtSvgMarkup } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-dom'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import './docx-watermark-dialog.css'
import { useModalKeys } from './docx-styles-modal-keys'

type Mode = 'none' | 'picture' | 'text'

const SCALES = [500, 200, 150, 100, 50]
const SIZES = [36, 40, 44, 48, 54, 60, 66, 72, 80, 90, 96, 105, 120, 144]
const DEFAULT_COLOR = 'C0C0C0'
const DEFAULT_FONT = 'Calibri'
const PICKABLE_MIME = new Set(['image/png', 'image/jpeg', 'image/gif'])

export interface WatermarkDialogCurrent {
  text: string | null
  style: Omit<WatermarkSpec, 'text'> | null
  picture: PictureWatermarkSpec | null
  /** the saved document's watermark shape (parsed header image), used when nothing is pending */
  docImage?: HfImage | null
}

/** section geometry in points; null falls back to Letter with 1in margins */
export interface WatermarkPageBox {
  pageWidthPt: number
  pageHeightPt: number
  marginWidthPt: number
  marginHeightPt: number
}

const LETTER: WatermarkPageBox = {
  pageWidthPt: 612,
  pageHeightPt: 792,
  marginWidthPt: 468,
  marginHeightPt: 648,
}

let inkCtx: CanvasRenderingContext2D | null | undefined

/** glyph ink box of the string at `sizePt`, i.e. the shape box Word gives an explicit Size */
function inkBoxPt(spec: WatermarkSpec, sizePt: number): { widthPt: number; heightPt: number } {
  if (inkCtx === undefined) inkCtx = document.createElement('canvas').getContext('2d')
  const fallback = { widthPt: sizePt * 0.6 * spec.text.length, heightPt: sizePt * 0.72 }
  if (!inkCtx) return fallback
  inkCtx.font = `${spec.italic ? 'italic' : 'normal'} ${spec.bold ? 'bold' : 'normal'} ${sizePt}px "${spec.fontFamily ?? DEFAULT_FONT}", sans-serif`
  const m = inkCtx.measureText(spec.text)
  const w = (m.actualBoundingBoxLeft ?? 0) + (m.actualBoundingBoxRight ?? m.width)
  const h = (m.actualBoundingBoxAscent ?? 0) + (m.actualBoundingBoxDescent ?? 0)
  if (!(w > 0) || !(h > 0)) return fallback
  const r = (v: number) => Math.round(v * 100) / 100
  return { widthPt: r(w), heightPt: r(h) }
}

const AUTO_BOX_HEIGHTS = [247.45, 131.95]

/** the Size a saved WordArt box was measured at; 'auto' for Word's auto boxes */
function sizeOfBox(spec: WatermarkSpec, heightPt: number): number | 'auto' {
  if (AUTO_BOX_HEIGHTS.some((h) => Math.abs(h - heightPt) < 0.5)) return 'auto'
  const perPt = inkBoxPt(spec, 100).heightPt / 100
  return perPt > 0 ? Math.max(1, Math.round(heightPt / perPt)) : 'auto'
}

/** parsed header shape → the dialog's text settings */
function textFromDocImage(img: HfImage): WatermarkSpec | null {
  const wa = img.wordArt
  if (!wa) return null
  const spec: WatermarkSpec = {
    text: wa.text,
    fontFamily: wa.fontFamily ?? DEFAULT_FONT,
    colorHex: wa.colorHex,
    opacity: wa.opacity,
    diagonal: (img.rotationDeg ?? 0) !== 0,
    ...(wa.bold ? { bold: true } : {}),
    ...(wa.italic ? { italic: true } : {}),
  }
  const heightPt = (img.heightPx ?? 0) * 0.75
  const size = heightPt > 0 ? sizeOfBox(spec, heightPt) : 'auto'
  if (size !== 'auto') {
    spec.sizePt = size
    spec.boxPt = inkBoxPt(spec, size)
  }
  return spec
}

/** parsed picture frame → picture settings; the natural size needs a decode, so async */
async function pictureFromDocImage(
  img: HfImage,
  box: WatermarkPageBox,
): Promise<PictureWatermarkSpec | null> {
  const m = /^data:(image\/(?:png|jpeg|gif));base64,(.*)$/s.exec(img.dataUrl)
  if (!m) return null
  const natural = await imageSizeOf(img.dataUrl)
  const spec: PictureWatermarkSpec = {
    image: {
      base64: m[2]!,
      mime: m[1] as PictureWatermarkSpec['image']['mime'],
      widthPx: natural.width,
      heightPx: natural.height,
    },
    washout: Boolean(img.washout),
  }
  const naturalWPt = (natural.width * 72) / 96
  const naturalHPt = (natural.height * 72) / 96
  const autoFactor = Math.min(box.marginWidthPt / naturalWPt, box.marginHeightPt / naturalHPt)
  const factor = ((img.widthPx ?? 0) * 0.75) / naturalWPt
  if (factor > 0 && Math.abs(factor - autoFactor) > 0.01) spec.scale = Math.round(factor * 100)
  return spec
}

export function WatermarkDialog({
  current,
  presets,
  pageBox,
  onApply,
  onClose,
  pickImage,
}: {
  current: WatermarkDialogCurrent
  presets: string[]
  pageBox: WatermarkPageBox | null
  onApply: (spec: Watermark | null) => void
  onClose: () => void
  pickImage: () => Promise<PictureWatermarkSpec["image"] | null>
}) {
  const { t, lang } = useI18n()
  const modalKeys = useModalKeys(onClose)
  const box = pageBox ?? LETTER
  // pending edits win; otherwise the saved shape seeds the fields (text style is
  // not kept on the file context, only its text is)
  const docText = !current.picture && !current.style && current.docImage?.wordArt
  const docPicture = !current.picture && !current.text && current.docImage?.watermark
  const cur: Partial<WatermarkSpec> =
    current.style ?? (docText ? (textFromDocImage(current.docImage!) ?? {}) : {})

  const [mode, setMode] = useState<Mode>(
    current.picture || docPicture ? 'picture' : current.text ? 'text' : 'none',
  )
  const [image, setImage] = useState<PictureWatermarkSpec['image'] | null>(
    current.picture?.image ?? null,
  )
  const [scale, setScale] = useState<number | 'auto'>(current.picture?.scale ?? 'auto')
  const [washout, setWashout] = useState(
    current.picture
      ? current.picture.washout !== false
      : !docPicture || Boolean(current.docImage?.washout),
  )
  useEffect(() => {
    if (!docPicture) return
    let alive = true
    void pictureFromDocImage(current.docImage!, box).then((spec) => {
      if (!alive || !spec) return
      setImage(spec.image)
      setScale(spec.scale ?? 'auto')
      setWashout(spec.washout !== false)
    })
    return () => {
      alive = false
    }
    // seeds once from the shape the dialog opened on
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [text, setText] = useState(current.text ?? presets[0] ?? 'DRAFT')
  const [font, setFont] = useState(cur.fontFamily ?? DEFAULT_FONT)
  const [size, setSize] = useState<number | 'auto'>(cur.sizePt ?? 'auto')
  const [bold, setBold] = useState(cur.bold ?? false)
  const [italic, setItalic] = useState(cur.italic ?? false)
  const [transparency, setTransparency] = useState(Math.round((1 - (cur.opacity ?? 0.5)) * 100))
  const [color, setColor] = useState((cur.colorHex ?? DEFAULT_COLOR).replace(/^#/, ''))
  const [diagonal, setDiagonal] = useState(cur.diagonal !== false)
  const [pickError, setPickError] = useState(false)
  const [applyError, setApplyError] = useState('')
  const [picking, setPicking] = useState(false)
  const alive = useRef(true), pickGeneration = useRef(0)
  useEffect(() => () => { alive.current = false; pickGeneration.current++ }, [])

  const fonts = fontFamiliesFor(lang)
  const fontOptions = fonts.includes(font) ? fonts : [font, ...fonts]

  const textSpec = (): WatermarkSpec | null => {
    const trimmed = text.trim()
    if (!trimmed) return null
    const spec: WatermarkSpec = {
      text: trimmed,
      fontFamily: font,
      colorHex: color.toUpperCase(),
      opacity: Math.round((1 - transparency / 100) * 100) / 100,
      diagonal,
      ...(bold ? { bold: true } : {}),
      ...(italic ? { italic: true } : {}),
    }
    if (size !== 'auto') {
      spec.sizePt = size
      spec.boxPt = inkBoxPt(spec, size)
    }
    return spec
  }
  const pictureSpec = (): PictureWatermarkSpec | null =>
    image ? { image, ...(scale === 'auto' ? {} : { scale }), washout } : null

  const resolved: Watermark | null =
    mode === 'text' ? textSpec() : mode === 'picture' ? pictureSpec() : null
  const canApply = mode === 'none' || resolved !== null

  const pick = async () => {
    const generation = ++pickGeneration.current
    setPicking(true)
    try {
      const picked = await pickImage()
      if (!alive.current || generation !== pickGeneration.current) return
      if (picked) { setImage(picked); setPickError(false) }
    } catch { if (alive.current && generation === pickGeneration.current) setPickError(true) }
    finally { if (alive.current && generation === pickGeneration.current) setPicking(false) }
  }

  const submit = () => {
    if (!canApply || picking) return
    try { onApply(resolved); onClose() } catch (error) { setApplyError(error instanceof Error ? error.message : String(error)) }
  }

  const previewImage: HfImage | null =
    resolved === null
      ? null
      : 'image' in resolved
        ? pictureWatermarkPreviewImage(resolved, {
            widthPt: box.marginWidthPt,
            heightPt: box.marginHeightPt,
          })
        : textWatermarkPreviewImage(resolved)

  const textOn = mode === 'text'
  const picOn = mode === 'picture'

  return (
    <div
      className="modal-backdrop"
      ref={modalKeys.ref}
      onKeyDown={modalKeys.onKeyDown}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="modal watermark-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('ribbonWatermarkDialogTitle')}
      >
        <h2>{t('ribbonWatermarkDialogTitle')}</h2>
        <div className="wm-body">
          <div className="wm-form">
            <label className="wm-mode">
              <input type="radio" checked={mode === 'none'} onChange={() => { pickGeneration.current++; setPicking(false); setMode('none') }} />
              {t('ribbonWatermarkNone')}
            </label>

            <label className="wm-mode">
              <input type="radio" checked={picOn} onChange={() => setMode('picture')} />
              {t('ribbonWatermarkPicture')}
            </label>
            <div className="wm-fields" aria-disabled={!picOn}>
              <div className="wm-row">
                <button className="btn-ghost wm-pick" disabled={!picOn || picking} onClick={() => void pick()}>
                  {t('ribbonWatermarkSelectPicture')}
                </button>
                <span className="wm-pick-name">
                  {image
                    ? `${image.widthPx} × ${image.heightPx} px`
                    : t('ribbonWatermarkNoPicture')}
                </span>
              </div>
              {pickError && <div className="modal-error">{t('ribbonImageLoadFail')}</div>}
              <div className="wm-row">
                <span className="wm-label">{t('ribbonWatermarkScale')}</span>
                <select
                  aria-label={t('ribbonWatermarkScale')}
                  disabled={!picOn}
                  value={scale}
                  onChange={(e) =>
                    setScale(e.target.value === 'auto' ? 'auto' : Number(e.target.value))
                  }
                >
                  <option value="auto">{t('ribbonWatermarkAuto')}</option>
                  {(scale === 'auto' || SCALES.includes(scale)
                    ? SCALES
                    : [...SCALES, scale].sort((a, b) => b - a)
                  ).map((s) => (
                    <option key={s} value={s}>
                      {s}%
                    </option>
                  ))}
                </select>
                <label className="wm-check">
                  <input
                    type="checkbox"
                    disabled={!picOn}
                    checked={washout}
                    onChange={(e) => setWashout(e.target.checked)}
                  />
                  {t('ribbonWatermarkWashout')}
                </label>
              </div>
            </div>

            <label className="wm-mode">
              <input type="radio" checked={textOn} onChange={() => { pickGeneration.current++; setPicking(false); setMode('text') }} />
              {t('ribbonWatermarkText')}
            </label>
            <div className="wm-fields" aria-disabled={!textOn}>
              <div className="wm-row">
                <input
                  type="text"
                  aria-label={t('ribbonWatermarkText')}
                  list="wm-text-presets"
                  disabled={!textOn}
                  value={text}
                  placeholder={t('ribbonWatermarkPh')}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && e.nativeEvent.keyCode !== 229) { e.preventDefault(); submit() } }}
                  autoFocus={textOn}
                />
                <datalist id="wm-text-presets">
                  {presets.map((p) => (
                    <option key={p} value={p} />
                  ))}
                </datalist>
              </div>
              <div className="wm-row">
                <span className="wm-label">{t('ribbonWatermarkFont')}</span>
                <select aria-label={t('ribbonWatermarkFont')} disabled={!textOn} value={font} onChange={(e) => setFont(e.target.value)}>
                  {fontOptions.map((f) => (
                    <option key={f} value={f} style={{ fontFamily: f }}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>
              <div className="wm-row">
                <span className="wm-label">{t('ribbonWatermarkSize')}</span>
                <select
                  className="wm-size"
                  aria-label={t('ribbonWatermarkSize')}
                  disabled={!textOn}
                  value={size}
                  onChange={(e) =>
                    setSize(e.target.value === 'auto' ? 'auto' : Number(e.target.value))
                  }
                >
                  <option value="auto">{t('ribbonWatermarkAuto')}</option>
                  {(size === 'auto' || SIZES.includes(size)
                    ? SIZES
                    : [...SIZES, size].sort((a, b) => a - b)
                  ).map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                <label className="wm-check">
                  <input
                    type="checkbox"
                    disabled={!textOn}
                    checked={bold}
                    onChange={(e) => setBold(e.target.checked)}
                  />
                  {t('appFontBold')}
                </label>
                <label className="wm-check">
                  <input
                    type="checkbox"
                    disabled={!textOn}
                    checked={italic}
                    onChange={(e) => setItalic(e.target.checked)}
                  />
                  {t('appFontItalic')}
                </label>
              </div>
              <div className="wm-row">
                <span className="wm-label">{t('ribbonWatermarkTransparency')}</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  disabled={!textOn}
                  value={transparency}
                  onChange={(e) => setTransparency(Number(e.target.value))}
                  aria-label={t('ribbonWatermarkTransparency')}
                />
                <input
                  type="number"
                  aria-label={t('ribbonWatermarkTransparency')}
                  className="wm-pct"
                  min={0}
                  max={100}
                  disabled={!textOn}
                  value={transparency}
                  onChange={(e) =>
                    setTransparency(Math.max(0, Math.min(100, Number(e.target.value) || 0)))
                  }
                />
                <span className="wm-unit">%</span>
              </div>
              <div className="wm-row">
                <span className="wm-label">{t('ribbonWatermarkFontColor')}</span>
                <input
                  type="color"
                  className="font-color-input wm-color"
                  disabled={!textOn}
                  value={`#${color}`}
                  onChange={(e) => setColor(e.target.value.slice(1))}
                  aria-label={t('ribbonWatermarkFontColor')}
                />
              </div>
              <div className="wm-row">
                <span className="wm-label">{t('ribbonWatermarkOrientation')}</span>
                <label className="wm-check">
                  <input
                    type="radio"
                    disabled={!textOn}
                    checked={!diagonal}
                    onChange={() => setDiagonal(false)}
                  />
                  {t('ribbonWatermarkHorizontal')}
                </label>
                <label className="wm-check">
                  <input
                    type="radio"
                    disabled={!textOn}
                    checked={diagonal}
                    onChange={() => setDiagonal(true)}
                  />
                  {t('ribbonWatermarkDiagonal')}
                </label>
              </div>
            </div>
          </div>
          <WatermarkPagePreview box={box} image={previewImage} />
        </div>
        {applyError && <p role="alert" tabIndex={0}>{applyError}</p>}
        <div className="modal-actions">
          <button className="btn-ghost" onClick={onClose}>
            {t('appCancel')}
          </button>
          <button className="btn-primary" disabled={!canApply || picking} onClick={submit}>
            {t('appOk')}
          </button>
        </div>
      </div>
    </div>
  )
}

const PREVIEW_HEIGHT_PX = 340
const PREVIEW_LINES = 36

/** scaled page: grey body lines inside the margin box, the watermark centered on it */
function WatermarkPagePreview({ box, image }: { box: WatermarkPageBox; image: HfImage | null }) {
  const k = PREVIEW_HEIGHT_PX / box.pageHeightPt
  const pageW = box.pageWidthPt * k
  const marginW = box.marginWidthPt * k
  const marginH = box.marginHeightPt * k
  const [svg, setSvg] = useState('')
  // text ink is measured against document fonts, which may still be loading
  useEffect(() => {
    if (!image?.wordArt) {
      setSvg('')
      return
    }
    setSvg(wordArtSvgMarkup(image))
    let alive = true
    void document.fonts?.ready.then(() => alive && setSvg(wordArtSvgMarkup(image)))
    return () => {
      alive = false
    }
  }, [image])
  const wmW = (image?.widthPx ?? 0) * 0.75 * k
  const wmH = (image?.heightPx ?? 0) * 0.75 * k
  const wmStyle: React.CSSProperties = {
    width: wmW,
    height: wmH,
    left: (marginW - wmW) / 2,
    top: (marginH - wmH) / 2,
    ...(image?.rotationDeg ? { transform: `rotate(${image.rotationDeg}deg)` } : {}),
    ...(image?.washout ? { filter: hfWashoutFilter(image.washout) } : {}),
  }
  return (
    <div className="wm-preview" style={{ width: pageW, height: PREVIEW_HEIGHT_PX }}>
      <div
        className="wm-preview-margin"
        style={{
          width: marginW,
          height: marginH,
          left: (pageW - marginW) / 2,
          top: (PREVIEW_HEIGHT_PX - marginH) / 2,
        }}
      >
        {image &&
          (image.wordArt ? (
            <span
              className="wm-preview-mark"
              style={wmStyle}
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          ) : (
            <img className="wm-preview-mark" alt="" src={image.dataUrl} style={wmStyle} />
          ))}
        <div className="wm-preview-lines">
          {Array.from({ length: PREVIEW_LINES }, (_, i) => (
            <span key={i} style={i % 4 === 3 ? { width: '55%' } : undefined} />
          ))}
        </div>
      </div>
    </div>
  )
}

function imageSizeOf(dataUrl: string): Promise<{width:number;height:number}> {
  return new Promise((resolve,reject)=>{ const image=new Image(); image.onload=()=>image.naturalWidth&&image.naturalHeight?resolve({width:image.naturalWidth,height:image.naturalHeight}):reject(Error('图片尺寸无效'));image.onerror=()=>reject(Error('图片加载失败'));image.src=dataUrl })
}
/** 浏览器授权文件选择，来源/草稿身份仍由宿主apply快照核验。 */
export function openDocxWatermarkSourceDialog(current:WatermarkDialogCurrent,pageBox:WatermarkPageBox,onApply:(value:Watermark|null)=>void,returnFocus:HTMLElement){
 const host=document.createElement('div');host.className='docx-native docx-watermark-source-host';document.body.append(host)
 const root=createRoot(host);let closed=false;const pendingPicks=new Set<(value:PictureWatermarkSpec['image']|null)=>void>()
 const close=()=>{if(closed)return;closed=true;for(const settle of pendingPicks)settle(null);pendingPicks.clear();queueMicrotask(()=>{root.unmount();host.remove();if(returnFocus.isConnected)returnFocus.focus()})}
 const pickImage=()=>new Promise<PictureWatermarkSpec['image']|null>((resolve,reject)=>{
  const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/gif';input.hidden=true;host.append(input)
  let settled=false;const finish=(value:PictureWatermarkSpec['image']|null)=>{if(settled)return;settled=true;pendingPicks.delete(finish);input.remove();resolve(value)};pendingPicks.add(finish)
  input.addEventListener('cancel',()=>finish(null));input.addEventListener('change',()=>{const file=input.files?.[0];if(!file){finish(null);return}if(!PICKABLE_MIME.has(file.type)||file.size>8*1024*1024){input.remove();pendingPicks.delete(finish);reject(Error('图片格式或大小不支持'));return}
   const reader=new FileReader();reader.onerror=()=>{input.remove();pendingPicks.delete(finish);reject(Error('图片读取失败'))};reader.onload=()=>{void (async()=>{try{const dataUrl=String(reader.result),natural=await imageSizeOf(dataUrl);if(closed){finish(null);return}finish({base64:dataUrl.split(',')[1]!,mime:file.type as PictureWatermarkSpec['image']['mime'],widthPx:natural.width,heightPx:natural.height})}catch(error){input.remove();pendingPicks.delete(finish);reject(error)}})()};reader.readAsDataURL(file)
  });input.click()
 })
 flushSync(()=>root.render(<WatermarkDialog current={current} presets={['机密','严禁复制','草稿','样本','CONFIDENTIAL','DRAFT']} pageBox={pageBox} pickImage={pickImage} onApply={value=>{if(!closed)onApply(value)}} onClose={close}/>))
 return close
}
