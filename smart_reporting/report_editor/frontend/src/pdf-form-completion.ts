import type { NativeOperation } from './native-draft'

export interface PdfReadableFormWidget {
  id?: string; subtype?: string; hidden?: boolean; fieldType?: string; fieldName?: string; fieldValue?: unknown
  required?: boolean; readOnly?: boolean; pushButton?: boolean; checkBox?: boolean; radioButton?: boolean; rect?: number[]
}

/** GenOffice form-catalog.ts normalizes each visible page's Widgets by top then left. */
export function orderedPdfFormWidgets(annotations: readonly PdfReadableFormWidget[], removed: ReadonlySet<unknown>) {
  return annotations.filter(widget => widget.subtype === 'Widget' && !widget.readOnly && !widget.hidden
    && !widget.pushButton && widget.fieldName && widget.rect?.length === 4 && !removed.has(widget.id))
    .sort((a,b) => b.rect![3] - a.rect![3] || a.rect![0] - b.rect![0])
}

/** GenOffice form-catalog.ts and App.tsx check visible, editable required fields using staged values. */
export function missingRequiredPdfFields(
  pages: readonly {pageId: string; annotations: readonly PdfReadableFormWidget[]}[],
  operations: readonly NativeOperation[],
) {
  const values = new Map(operations.filter(op => op.kind === 'setFormValue').map(op => [op.name, op]))
  const removed = new Set(operations.filter(op => op.kind === 'removeFormWidget').map(op => op.widgetId))
  const fields = new Map<string, {name: string; pageId: string; filled: boolean}>()
  for (const page of pages) {
    const widgets = orderedPdfFormWidgets(page.annotations, removed).filter(widget => widget.required)
    for (const widget of widgets) {
      const name = widget.fieldName!
      const type = widget.fieldType
      const edit = values.get(name)
      const raw = edit ? edit.value : widget.fieldValue
      const value = Array.isArray(raw) ? raw[0] : raw
      let filled: boolean
      if (type === 'Sig') filled = false
      else if (type === 'Btn' && widget.checkBox) filled = edit ? edit.checked === true : typeof value === 'string' && value !== '' && value !== 'Off'
      else if (type === 'Tx' || type === 'Ch' || (type === 'Btn' && widget.radioButton)) filled = typeof value === 'string' && value.trim().length > 0 && (type !== 'Btn' || value !== 'Off')
      else continue
      const existing = fields.get(name)
      if (existing) existing.filled ||= filled
      else fields.set(name, {name,pageId:page.pageId,filled})
    }
  }
  return [...fields.values()].filter(field => !field.filled)
}
