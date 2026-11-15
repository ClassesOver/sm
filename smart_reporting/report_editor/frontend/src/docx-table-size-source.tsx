import type { DocxTableCommands, DocxTableDimensionAction } from './docx-tables'
import { LengthInput } from './vendor/genoffice-docs/apps/docs/src/renderer/components/LengthInput'
import { zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'

/** GenOffice Table Layout LengthInput fields with source-bound sizing commits. */
export function DocxTableSizeSource({ commands, editable }: { commands: DocxTableCommands; editable: boolean }) {
  const field = (action: DocxTableDimensionAction, label: string, rowHeight = false) => {
    const dimension = commands.dimension?.(action)
    const reason = editable ? (dimension ? null : commands.reason(action)) : '当前文档不可编辑或正在保存'
    return (
      <label key={`${action}:${dimension?.key ?? ''}`} title={reason ?? label}>
        {label}
        <LengthInput value={dimension?.value ?? null} min={rowHeight ? 0 : 1}
          max={dimension?.max} allowEmpty={rowHeight} placeholder={zh.ribbonAuto}
          disabled={!editable || !dimension} ariaLabel={label}
          onCommit={twips => dimension?.commit(twips)} />
      </label>
    )
  }
  return <>{field('table-row-height', zh.ribbonRowHeight, true)}{field('table-column-width', zh.ribbonColumnWidth)}</>
}
