/// Read conditional-formatting rules back out of a worksheet part.
///
/// Self-colored rules (dataBar / colorScale) round-trip into the model so the
/// grid can render them. cellIs stays write-only — it points at dxf styles
/// the stylesheet reader does not migrate — and iconSet needs a Univer
/// icon-type table; both are parsed by nothing here on purpose.

import type { CfColorScaleRule, CfDataBarRule, Cfvo } from './cf-schemas'

export type CfReadableRule = CfDataBarRule | CfColorScaleRule

function attributeOf(attributes: string, name: string): string | undefined {
  return attributes.match(new RegExp(`(?:^|\\s)${name}="([^"]*)"`))?.[1]
}

function cfvoOf(attributes: string): Cfvo {
  const type = (attributeOf(attributes, 'type') ?? 'num') as Cfvo['type']
  const raw = attributeOf(attributes, 'val')
  if (raw === undefined || raw === '') return { type }
  const numeric = Number(raw)
  return { type, ...(Number.isFinite(numeric) ? { value: numeric } : { value: raw }) }
}

/// OOXML rgb is ARGB; the grid only wants #RRGGBB, so the alpha byte is
/// dropped (FF is the normal opaque case and transparent bars are useless).
function colorOf(rgb: string | undefined): string | undefined {
  if (rgb === undefined) return undefined
  const hex = rgb.length === 8 ? rgb.slice(2) : rgb
  return /^[0-9A-Fa-f]{6}$/.test(hex) ? `#${hex.toUpperCase()}` : undefined
}

export function readCfRules(sheetXml: string, sheetName: string): CfReadableRule[] {
  const rules: CfReadableRule[] = []
  for (const block of sheetXml.matchAll(
    /<conditionalFormatting\b([^>]*)>([\s\S]*?)<\/conditionalFormatting>/g,
  )) {
    const sqref = attributeOf(block[1] ?? '', 'sqref')
    if (sqref === undefined || sqref === '') continue
    for (const entry of (block[2] ?? '').matchAll(/<cfRule\b([^>]*)>([\s\S]*?)<\/cfRule>/g)) {
      const attributes = entry[1] ?? ''
      const body = entry[2] ?? ''
      const stopIfTrue = attributeOf(attributes, 'stopIfTrue') === '1'
      const type = attributeOf(attributes, 'type')
      if (type === 'dataBar') {
        const dataBar = body.match(/<dataBar\b([^>]*)>([\s\S]*?)<\/dataBar>/)
        if (!dataBar) continue
        const cfvos = [...(dataBar[2] ?? '').matchAll(/<cfvo\b([^>]*?)\/>/g)].map((m) =>
          cfvoOf(m[1] ?? ''),
        )
        const color = colorOf((dataBar[2] ?? '').match(/<color\b[^>]*\brgb="([^"]+)"/)?.[1])
        if (cfvos.length < 2 || color === undefined) continue
        const showValue =
          attributeOf(attributes, 'showValue') ?? attributeOf(dataBar[1] ?? '', 'showValue')
        rules.push({
          kind: 'dataBar',
          sheet: sheetName,
          sqref,
          min: cfvos[0]!,
          max: cfvos[1]!,
          color,
          ...(showValue === '0' || showValue === 'false' ? { showValue: false } : {}),
          ...(stopIfTrue ? { stopIfTrue: true } : {}),
        })
      } else if (type === 'colorScale') {
        const scale = body.match(/<colorScale\b[^>]*>([\s\S]*?)<\/colorScale>/)
        if (!scale) continue
        const inner = scale[1] ?? ''
        const cfvos = [...inner.matchAll(/<cfvo\b([^>]*?)\/>/g)].map((m) => cfvoOf(m[1] ?? ''))
        const colors = [...inner.matchAll(/<color\b[^>]*\brgb="([^"]+)"/g)]
          .map((m) => colorOf(m[1]))
          .filter((color): color is string => color !== undefined)
        if (cfvos.length < 2 || colors.length < 2 || colors.length !== cfvos.length) continue
        rules.push({
          kind: 'colorScale',
          sheet: sheetName,
          sqref,
          stops: cfvos.map((cfvo, index) => ({ cfvo, color: colors[index]! })),
          ...(stopIfTrue ? { stopIfTrue: true } : {}),
        })
      }
    }
  }
  return rules
}
