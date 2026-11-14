/**
 * Format Background pane (PowerPoint's "Format Background"): solid / gradient / picture
 * background for the current slide, a "hide background graphics" toggle, plus
 * apply-to-all and reset-background. Shares the right dock with the other panes.
 *
 * Fill edits apply live to the current slide (like PowerPoint); "apply to all"
 * re-applies the current slide's background to every slide.
 */
import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { SlidesFormatColorWell } from './slides-chart-format-pane'
import './slides-background-pane.css'
import type { RenderSlide } from '@genoffice/pptx-render'




/** Background op without the fields App fills in (slideIndex / sourceSlideIndex / fitWidthPx). */
export type BackgroundPaneOp =
  | { kind: 'solid'; color: string }
  | { kind: 'gradient'; from: string; to: string; angleDeg?: number; radial?: boolean }
  | { kind: 'image'; mode: 'stretch' | 'tile'; pick?: boolean }
  | { kind: 'reset' }
  | { kind: 'hideGraphics'; hidden: boolean }

interface Props {
  slide: RenderSlide | undefined
  /** Dispatch a background edit; allSlides=true targets every slide */
  onApply: (op: BackgroundPaneOp, allSlides?: boolean) => void
  onCollapse: () => void
  locked?: boolean
}

type FillMode = 'solid' | 'gradient' | 'image'

const GRADIENT_DIRECTIONS = [
  ['→', 0, false],
  ['↓', 90, false],
  ['↘', 45, false],
  ['◎', 0, true],
] as const

export function FormatBackgroundPane({ slide, onApply, onCollapse, locked=false }: Props) {
  const t = (key: string) => labels[key] ?? key
  const bg = slide?.background
  const currentMode: FillMode =
    bg?.kind === 'gradient' ? 'gradient' : bg?.kind === 'image' ? 'image' : 'solid'
  // The tab the user picked (may differ from the slide's fill until an edit applies)
  const [pickedMode, setPickedMode] = useState<FillMode | null>(null)
  const mode = pickedMode ?? currentMode

  const solidColor = bg?.kind === 'solid' ? toHex6(bg.color) : '#ffffff'
  const gradStops = bg?.kind === 'gradient' ? bg.stops : null
  const [gradFromPick, setGradFrom] = useState<string | null>(null)
  const [gradToPick, setGradTo] = useState<string | null>(null)
  const gradFrom = gradFromPick ?? (gradStops ? toHex6(gradStops[0]!.color) : '#4472c4')
  const gradTo = gradToPick ?? (gradStops ? toHex6(gradStops.at(-1)!.color) : '#ffffff')
  const gradAngle = bg?.kind === 'gradient' ? Math.round(bg.angleDeg) : 0
  const gradRadial = bg?.kind === 'gradient' && !!bg.radial
  const imageMode = bg?.kind === 'image' ? (bg.mode ?? 'stretch') : 'stretch'

  const debounced = (op: BackgroundPaneOp) => onApply(op)

  const gradientOp = (from: string, to: string, angleDeg: number, radial: boolean): BackgroundPaneOp => ({
    kind: 'gradient',
    from,
    to,
    angleDeg,
    ...(radial ? { radial: true } : {}),
  })

  /** Re-apply the current slide's background fill (for "apply to all"). */
  const currentFillOp = (): BackgroundPaneOp | null => {
    if (!bg) return null
    if (bg.kind === 'solid') return { kind: 'solid', color: toHex6(bg.color) }
    if (bg.kind === 'gradient') return gradientOp(gradFrom, gradTo, gradAngle, gradRadial)
    if (bg.kind === 'image') return { kind: 'image', mode: imageMode, pick: false }
    return null
  }

  const hasDoc = !!slide

  return (
    <aside className="format-pane">
      <div className="ai-panel-header">
        <span className="ai-panel-title">{t('paneBgTitle')}</span>
        <div className="ai-panel-header-actions">
          <button
            className="ai-header-btn"
            onClick={onCollapse}
            data-tip={t('paneFormatClose')}
            aria-label={t('paneFormatClose')}
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
      </div>

      {!hasDoc ? (
        <div className="fp-empty">{t('paneBgEmpty')}</div>
      ) : (
        <div className="fp-body">
          <div className="fp-section">{t('paneFormatFill')}</div>
          <div className="fp-row">
            <button
              className={`fp-btn fp-btn-wrap ${mode === 'solid' ? 'active' : ''}`}
              disabled={locked}
              onClick={() => {
                setPickedMode('solid')
                if (currentMode !== 'solid') onApply({ kind: 'solid', color: solidColor })
              }}
            >
              {t('paneBgSolid')}
            </button>
            <button
              className={`fp-btn fp-btn-wrap ${mode === 'gradient' ? 'active' : ''}`}
              disabled={locked}
              onClick={() => {
                setPickedMode('gradient')
                if (currentMode !== 'gradient')
                  onApply(gradientOp(gradFrom, gradTo, gradAngle, gradRadial))
              }}
            >
              {t('paneBgGradient')}
            </button>
            <button
              className={`fp-btn fp-btn-wrap ${mode === 'image' ? 'active' : ''}`}
              disabled={locked}
              onClick={() => {
                setPickedMode('image')
                if (currentMode !== 'image') onApply({ kind: 'image', mode: 'stretch', pick: true })
              }}
            >
              {t('paneBgImage')}
            </button>
          </div>

          {mode === 'solid' && (
            <div className="fp-row">
              <SlidesFormatColorWell point="background" disabled={locked}
                value={solidColor}
                label={t('paneFormatSolidFill')}
                onPick={(hex) => debounced({ kind: 'solid', color: hex })}
              />
            </div>
          )}

          {mode === 'gradient' && (
            <div className="fp-row">
              <SlidesFormatColorWell point="background" disabled={locked}
                value={gradFrom}
                label={t('paneFormatGradientFrom')}
                onPick={(hex) => {
                  setGradFrom(hex)
                  debounced(gradientOp(hex, gradTo, gradAngle, gradRadial))
                }}
              />
              <SlidesFormatColorWell point="background" disabled={locked}
                value={gradTo}
                label={t('paneFormatGradientTo')}
                onPick={(hex) => {
                  setGradTo(hex)
                  debounced(gradientOp(gradFrom, hex, gradAngle, gradRadial))
                }}
              />
              {GRADIENT_DIRECTIONS.map(([label, angleDeg, radial]) => (
                <button
                  key={label}
                  className={`fp-btn ${
                    currentMode === 'gradient' &&
                    (radial ? gradRadial : !gradRadial && gradAngle === angleDeg)
                      ? 'active'
                      : ''
                  }`}
                  data-tip={radial ? t('paneFormatGradientRadial') : `${angleDeg}°`}
                  aria-label={radial ? t('paneFormatGradientRadial') : `${angleDeg}°`}
                  disabled={locked}
                  onClick={() => onApply(gradientOp(gradFrom, gradTo, angleDeg, radial))}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {mode === 'image' && (
            <>
              {bg?.kind === 'image' && bg.dataUrl && (
                <div className="fp-row">
                  <img className="fp-bg-preview" src={bg.dataUrl} alt="" />
                </div>
              )}
              <div className="fp-row">
                <button
                  className="fp-btn"
                  disabled={locked}
                  onClick={() => onApply({ kind: 'image', mode: imageMode, pick: true })}
                >
                  {t('paneBgPickImage')}
                </button>
                {(
                  [
                    ['stretch', t('paneBgStretch')],
                    ['tile', t('paneBgTile')],
                  ] as const
                ).map(([m, label]) => (
                  <button
                    key={m}
                    className={`fp-btn ${bg?.kind === 'image' && imageMode === m ? 'active' : ''}`}
                    disabled={locked || bg?.kind !== 'image'}
                    onClick={() => onApply({ kind: 'image', mode: m, pick: false })}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </>
          )}

          <div className="fp-row">
            <label className="fp-check">
              <input
                type="checkbox"
                disabled={locked}
                checked={!!slide?.bgGraphicsHidden}
                onChange={(e) => onApply({ kind: 'hideGraphics', hidden: e.target.checked })}
              />
              <span>{t('paneBgHideGraphics')}</span>
            </label>
          </div>

          <div className="fp-section">{t('paneFormatActions')}</div>
          <div className="fp-row">
            <button
              className="fp-btn"
              disabled={locked || !currentFillOp()}
              onClick={() => {
                const op = currentFillOp()
                if (op) onApply(op, true)
              }}
            >
              {t('ribbonApplyToAll')}
            </button>
            <button
              className="fp-btn"
              disabled={locked || !slide?.bgOwn}
              data-tip={t('paneBgResetTip')}
              onClick={() => {
                setPickedMode(null)
                onApply({ kind: 'reset' })
              }}
            >
              {t('paneBgReset')}
            </button>
          </div>
        </div>
      )}
    </aside>
  )
}

function toHex6(c: string): string {
  const m = /^#?([0-9a-fA-F]{6})/.exec(c)
  return m ? `#${m[1]!.toLowerCase()}` : '#ffffff'
}

const labels: Record<string,string>={paneBgTitle:'设置背景格式',paneFormatClose:'关闭格式窗格',paneBgEmpty:'打开演示文稿后可设置页面背景',paneBgSolid:'纯色填充',paneBgGradient:'渐变填充',paneBgImage:'图片填充',paneBgPickImage:'选择图片…',paneBgStretch:'拉伸',paneBgTile:'平铺',paneBgHideGraphics:'隐藏背景图形',paneBgReset:'重置背景',paneBgResetTip:'删除本页自己的背景设置，恢复为版式/母版背景',paneFormatFill:'填充',paneFormatSolidFill:'纯色填充',paneFormatGradientFrom:'起始色',paneFormatGradientTo:'结束色',paneFormatGradientRadial:'径向',paneFormatActions:'操作',ribbonApplyToAll:'应用到全部'}
/** 源背景整族的宿主：颜色合并为单笔历史，切页丢弃未提交颜色。 */
export function createSlidesBackgroundPane(onApply:(op:BackgroundPaneOp,all?:boolean)=>void) {
 const element=document.createElement('section');element.className='slides-background-pane-host';element.hidden=true;element.setAttribute('aria-label','设置背景格式')
 const root=createRoot(element)
 let epoch=0
 let slide:RenderSlide|undefined,key='',locked=false,visible=false,disposed=false,error='',pending:BackgroundPaneOp|undefined,timer:ReturnType<typeof setTimeout>|undefined
 const cancel=()=>{clearTimeout(timer);timer=undefined;pending=undefined}
 function flush(){clearTimeout(timer);timer=undefined;if(!pending)return true;const op=pending;pending=undefined;try{onApply(op);error='';return true}catch(cause){error=cause instanceof Error?cause.message:'背景未能应用';render();return false}}
 function apply(op:BackgroundPaneOp,all?:boolean){
  if(disposed||locked)return
  if(all){const fill=pending??op;cancel();onApply(fill,true);return}
  if(op.kind==='solid'||op.kind==='gradient'){pending=op;clearTimeout(timer);timer=setTimeout(flush,200)}
  else{if(!flush())return;onApply(op,all)}
 }
 function close(){++epoch;cancel();visible=false;render()}
 function render(){element.hidden=!visible;flushSync(()=>root.render(visible?<div key={key} onKeyDown={event=>{if(event.currentTarget.contains(event.target as Node))event.stopPropagation()}}><FormatBackgroundPane slide={slide} onApply={apply} onCollapse={close} locked={locked}/><p role="alert">{error}</p></div>:null));element.querySelector<HTMLButtonElement>('[aria-label="关闭格式窗格"]')?.removeAttribute('disabled')}
 return {element,token:()=>epoch,open(next:RenderSlide,target:string){if(disposed)return;++epoch;cancel();slide=next;key=target;visible=true;render()},update(next:RenderSlide|undefined,target:string,nextLocked=false){if(disposed)return;if(target!==key){++epoch;cancel();key=target}slide=next;locked=nextLocked;if(visible)render()},setLocked(value:boolean){++epoch;cancel();locked=value;if(visible)render()},flush,cancel,close,dispose(){if(disposed)return;disposed=true;cancel();flushSync(()=>root.unmount());element.remove()}}
}
