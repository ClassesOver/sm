import { useEffect, useMemo, useState } from 'react'
import type { Editor } from '@tiptap/core'
import { latexToOmml, ommlToMathML } from '@genoffice/docx-engine'
import { t, useI18n, type StringKey } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/locale'
import { equationControls } from './docx-equations'
import './docx-equations.css'
import { useModalKeys } from './vendor/genoffice-docs/apps/docs/src/renderer/components/modal-keys'

/** Built-in equation library (the common preset set for the "Insert Equation" dropdown) */
export const BUILTIN_EQUATIONS: Array<{ name: string; nameKey: StringKey; latex: string }> = [
  { name: 'Area of Circle', nameKey: 'appEqCircleArea', latex: 'A = \\pi r^2' },
  {
    name: 'Binomial Theorem',
    nameKey: 'appEqBinomial',
    latex: '(x+a)^n = \\sum_{k=0}^{n} \\binom{n}{k} x^k a^{n-k}',
  },
  {
    name: 'Expansion of a Sum',
    nameKey: 'appEqSumExpansion',
    latex: '(1+x)^n = 1 + \\frac{nx}{1!} + \\frac{n(n-1)x^2}{2!} + \\cdots',
  },
  {
    name: 'Fourier Series',
    nameKey: 'appEqFourier',
    latex:
      'f(x) = a_0 + \\sum_{n=1}^{\\infty} \\left( a_n \\cos \\frac{n\\pi x}{L} + b_n \\sin \\frac{n\\pi x}{L} \\right)',
  },
  { name: 'Pythagorean Theorem', nameKey: 'appEqPythagorean', latex: 'a^2 + b^2 = c^2' },
  {
    name: 'Quadratic Formula',
    nameKey: 'appEqQuadratic',
    latex: 'x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}',
  },
  {
    name: 'Taylor Expansion',
    nameKey: 'appEqTaylor',
    latex:
      'e^x = 1 + \\frac{x}{1!} + \\frac{x^2}{2!} + \\frac{x^3}{3!} + \\cdots, -\\infty < x < \\infty',
  },
  {
    name: 'Trig Identity',
    nameKey: 'appEqTrigIdentity',
    latex:
      '\\sin \\alpha \\pm \\sin \\beta = 2 \\sin \\frac{1}{2} (\\alpha \\pm \\beta) \\cos \\frac{1}{2} (\\alpha \\mp \\beta)',
  },
]

/** Build an equation block from LaTeX and insert it (protected block, genXml goes through the save path) */
export function insertEquationFromLatex(editor: Editor, latex: string): void {
  const controls=equationControls(editor);if(!controls)throw new Error('公式编辑尚未就绪');controls.insert(latex,false)
}

/** Insert an inline equation at the cursor that flows with the text */
export function insertInlineEquationFromLatex(editor: Editor, latex: string): void {
  const controls=equationControls(editor);if(!controls)throw new Error('公式编辑尚未就绪');controls.insert(latex,true)
}

/** Equation re-edit target (inline = inline node; block = standalone protected equation block) */
export interface MathEditTarget {
  pos: number
  latex: string
  kind: 'inline' | 'block'
  formulaId?: string
}

/** MathML preview (returns null with an error message when the LaTeX is invalid) */
function previewOf(latex: string): { mathml: string } | { error: string } | null {
  if (!latex.trim()) return null
  try {
    const omml = latexToOmml(latex)
    const mathml = ommlToMathML(`<m:oMath>${omml}</m:oMath>`)
    return mathml ? { mathml } : { error: t('appPreviewUnavailable') }
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) }
  }
}

/** Insert Equation dialog: LaTeX input + live MathML preview, shared by the ribbon and the native menu */
export function EquationModal({
  editor,
  onClose,
  editTarget,
}: {
  editor: Editor
  onClose: () => void
  /** When provided, "re-edit equation" mode: update that node instead of inserting */
  editTarget?: MathEditTarget
}) {
  const { t } = useI18n()
  const modalKeys = useModalKeys(onClose)
  const [latex, setLatex] = useState(editTarget?.latex ?? '')
  const [inline, setInline] = useState(editTarget?.kind === 'inline')
  const preview = useMemo(() => previewOf(latex), [latex])
  const [error,setError]=useState('')
  const canInsert = preview !== null && 'mathml' in preview

  const insert = () => {
    if (!canInsert || !editor.isEditable) return
    try {
      if (editTarget) {
        const node=editor.state.doc.nodeAt(editTarget.pos)
        if(!node || editTarget.formulaId && node.attrs.nativeEquationId!==editTarget.formulaId)throw new Error('公式位置已变化，请重新打开编辑')
        const controls=equationControls(editor);if(!controls)throw new Error('公式编辑尚未就绪')
        controls.update(editTarget.pos,latex)
      } else if(inline) insertInlineEquationFromLatex(editor,latex)
      else insertEquationFromLatex(editor,latex)
    }catch(error){setError((error as Error).message);return}
    onClose()
  }

  return (
    <div
      className="modal-backdrop"
      ref={modalKeys.ref}
      onKeyDown={modalKeys.onKeyDown}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="modal equation-modal" role="dialog" aria-modal="true" aria-label={t('appInsertEquation')}>
        <h2>{t('appInsertEquation')}</h2>
        <label>
          LaTeX
          <input
            value={latex}
            onChange={(e) => setLatex(e.target.value)}
            placeholder={t('appLatexPlaceholder')}
            onKeyDown={(e) => e.key === 'Enter' && insert()}
            autoFocus
          />
        </label>
        <div className="equation-preview">
          {preview === null && (
            <span className="equation-preview-hint">{t('appLatexPreviewHint')}</span>
          )}
          {preview !== null && 'error' in preview && (
            <span className="equation-preview-error">{preview.error}</span>
          )}
          {preview !== null && 'mathml' in preview && (
            <span dangerouslySetInnerHTML={{ __html: preview.mathml }} />
          )}
        </div>
        {!editTarget && (
          <label className="equation-inline-toggle">
            <input type="checkbox" checked={inline} onChange={(e) => setInline(e.target.checked)} />
            {t('appInlineEquationToggle')}
          </label>
        )}
        {error ? <p role="alert">{error}</p> : null}
        <div className="modal-actions">
          <button className="btn-ghost" onClick={onClose}>
            {t('appCancel')}
          </button>
          <button className="btn-primary" disabled={!canInsert} onClick={insert}>
            {editTarget ? t('appUpdate') : t('appInsert')}
          </button>
        </div>
      </div>
    </div>
  )
}

/** Built-in equation gallery (ribbon Equation ▾ dropdown), with MathML thumbnail previews */
export function EquationGallery({
  editor,
  onPick,
  onCustom,
}: {
  editor: Editor
  onPick: () => void
  onCustom: () => void
}) {
  const { t } = useI18n()
  const [error,setError]=useState('')
  return (
    <div data-rb-panel="" className="equation-gallery">
      {BUILTIN_EQUATIONS.map((eq) => {
        const preview = previewOf(eq.latex)
        return (
          <button
            key={eq.nameKey}
            className="equation-gallery-item"
            data-tip={t(eq.nameKey)}
            onClick={() => {
              try { insertEquationFromLatex(editor, eq.latex);onPick() } catch(error){setError((error as Error).message)}
            }}
          >
            <span className="equation-gallery-name">{t(eq.nameKey)}</span>
            {preview !== null && 'mathml' in preview && (
              <span
                className="equation-gallery-preview"
                dangerouslySetInnerHTML={{ __html: preview.mathml }}
              />
            )}
          </button>
        )
      })}
      {error ? <p role="alert">{error}</p> : null}
      <button className="equation-gallery-custom" onClick={onCustom}>
        {t('appInsertNewEquation')}
      </button>
    </div>
  )
}

/** Full-source App-level re-edit listener stays mounted when ribbon tabs change. */
export function EquationEditListener({editor}:{editor:Editor}) {
 const [target,setTarget]=useState<MathEditTarget>()
 useEffect(()=>{const edit=(event:Event)=>{const value=(event as CustomEvent<MathEditTarget>).detail,node=editor.state.doc.nodeAt(value.pos);if(!node?.attrs.nativeEquationId||!equationControls(editor))return;setTarget({...value,formulaId:String(node.attrs.nativeEquationId)})};window.addEventListener('ai-docs-edit-inline-math',edit);return()=>window.removeEventListener('ai-docs-edit-inline-math',edit)},[editor])
 return target?<EquationModal editor={editor} editTarget={target} onClose={()=>setTarget(undefined)}/>:null
}
