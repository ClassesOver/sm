import { z } from 'zod'

import { parseAddress } from './cell-address'

export const OOXML_ICON_SETS = [
  '3Arrows', '3ArrowsGray', '3Flags', '3TrafficLights1', '3TrafficLights2', '3Signs',
  '3Symbols', '3Symbols2', '4Arrows', '4ArrowsGray', '4RedToBlack', '4Rating',
  '4TrafficLights', '5Arrows', '5ArrowsGray', '5Quarters', '5Rating',
] as const

const CELL_REFERENCE = '[$]?[A-Z]{1,3}[$]?[1-9][0-9]{0,6}'
const SQREF_PATTERN = new RegExp(`^${CELL_REFERENCE}(?::${CELL_REFERENCE})?( ${CELL_REFERENCE}(?::${CELL_REFERENCE})?)*$`)

export function isValidRuleSqref(sqref: string): boolean {
  if (sqref.length > 4096 || !SQREF_PATTERN.test(sqref)) return false
  return sqref.split(' ').every((range) => {
    const parts = range.split(':')
    const first = parseAddress(parts[0]!)
    const last = parseAddress(parts[1] ?? parts[0]!)
    return first.row <= last.row && first.column <= last.column &&
      last.row < 1_048_576 && last.column < 16_384
  })
}

const colorSchema = z.string().regex(/^#[0-9A-Fa-f]{6}$/, 'Not a valid #RRGGBB color.')
const ruleBase = {
  sheet: z.string().min(1).max(64),
  sqref: z.string().refine(isValidRuleSqref, 'Invalid or out-of-bounds sqref.'),
  stopIfTrue: z.boolean().optional(),
}

const thresholdShape = {
  type: z.enum(['num', 'percent', 'percentile', 'min', 'max', 'formula']),
  value: z.union([z.number().finite(), z.string().max(500)]).optional(),
}

type Threshold = { type: string; value?: number | string | undefined }

function validThreshold(threshold: Threshold): boolean {
  if (threshold.type === 'min' || threshold.type === 'max') return threshold.value === undefined
  if (threshold.type === 'formula') {
    return typeof threshold.value === 'string' && threshold.value.trim().length > 0
  }
  if (typeof threshold.value !== 'number' || !Number.isFinite(threshold.value)) return false
  return threshold.type === 'num' || (threshold.value >= 0 && threshold.value <= 100)
}

export const cfvoSchema = z.object(thresholdShape).strict()
  .refine(validThreshold, 'A threshold needs a finite numeric value, a nonempty formula, or a valueless min/max.')

export const cfColorStopSchema = z.object({ ...thresholdShape, color: colorSchema }).strict()
  .refine(validThreshold, 'Invalid color-scale threshold.')

export const cfIconThresholdSchema = z.object({
  ...thresholdShape,
  greaterThan: z.boolean().optional(),
}).strict().refine(validThreshold, 'Invalid icon-set threshold.')

function ascendingThresholds(thresholds: readonly Threshold[]): boolean {
  return thresholds.every((threshold, index) => {
    const previous = thresholds[index - 1]
    if (!previous || typeof threshold.value !== 'number' || typeof previous.value !== 'number') return true
    return threshold.type !== previous.type || previous.value <= threshold.value
  })
}

export const cfCellIsRuleSchema = z.object({
  ...ruleBase,
  operator: z.enum(['greaterThan', 'lessThan', 'equal', 'notEqual', 'greaterThanOrEqual', 'lessThanOrEqual', 'between', 'notBetween']),
  formula1: z.string().min(1).max(500),
  formula2: z.string().max(500).optional(),
  fontColor: colorSchema.optional(),
  fillColor: colorSchema.optional(),
  bold: z.boolean().optional(),
  italic: z.boolean().optional(),
  strike: z.boolean().optional(),
  underline: z.boolean().optional(),
}).strict().refine(
  (rule) => !['between', 'notBetween'].includes(rule.operator) || (rule.formula2?.trim().length ?? 0) > 0,
  'Between comparisons need formula2.',
)

export const cfColorScaleWireSchema = z.object({
  ...ruleBase,
  kind: z.literal('colorScale'),
  stops: z.array(cfColorStopSchema).min(2, 'A color scale needs two or three stops.').max(3),
}).strict().refine((rule) => ascendingThresholds(rule.stops), 'Color-scale thresholds must be ascending.')

export const cfColorScaleEngineSchema = z.object({
  ...ruleBase,
  kind: z.literal('colorScale'),
  stops: z.array(z.object({ cfvo: cfvoSchema, color: colorSchema }).strict())
    .min(2, 'A color scale needs two or three stops.').max(3),
}).strict().refine((rule) => ascendingThresholds(rule.stops.map((stop) => stop.cfvo)), 'Color-scale thresholds must be ascending.')

export const cfDataBarSchema = z.object({
  ...ruleBase,
  kind: z.literal('dataBar'),
  min: cfvoSchema,
  max: cfvoSchema,
  color: colorSchema,
  showValue: z.boolean().optional(),
  stopIfTrue: z.boolean().optional(),
}).strict().refine((rule) => ascendingThresholds([rule.min, rule.max]), 'Data-bar bounds must be ascending.')

export const cfIconSetSchema = z.object({
  ...ruleBase,
  kind: z.literal('iconSet'),
  iconSet: z.enum(OOXML_ICON_SETS, { error: 'This icon set cannot be saved to base OOXML.' }),
  thresholds: z.array(cfIconThresholdSchema).min(3).max(5),
  reverse: z.boolean().optional(),
  showValue: z.boolean().optional(),
  stopIfTrue: z.boolean().optional(),
}).strict().superRefine((rule, context) => {
  const count = Number(rule.iconSet[0])
  if (rule.thresholds.length !== count) {
    context.addIssue({ code: 'custom', path: ['thresholds'], message: `The ${rule.iconSet} icon set needs exactly ${count} thresholds.` })
  }
  if (!ascendingThresholds(rule.thresholds)) {
    context.addIssue({ code: 'custom', path: ['thresholds'], message: 'Icon thresholds must be ascending.' })
  }
})

export const conditionalFormatWireRuleSchema = z.union([
  cfCellIsRuleSchema, cfColorScaleWireSchema, cfDataBarSchema, cfIconSetSchema,
])

export const conditionalFormatEngineRuleSchema = z.union([
  cfCellIsRuleSchema, cfColorScaleEngineSchema, cfDataBarSchema, cfIconSetSchema,
])

export type Cfvo = z.infer<typeof cfvoSchema>
export type CfRule = z.infer<typeof cfCellIsRuleSchema>
export type CfColorScaleRule = z.infer<typeof cfColorScaleEngineSchema>
export type CfDataBarRule = z.infer<typeof cfDataBarSchema>
export type CfIconSetRule = z.infer<typeof cfIconSetSchema>
export type CfAnyRule = z.infer<typeof conditionalFormatEngineRuleSchema>
export type CfWireRule = z.infer<typeof conditionalFormatWireRuleSchema>

export function toEngineConditionalFormatRule(rule: CfWireRule): CfAnyRule {
  if (!('kind' in rule) || rule.kind !== 'colorScale') return rule
  return {
    kind: 'colorScale',
    sheet: rule.sheet,
    sqref: rule.sqref,
    ...(rule.stopIfTrue !== undefined ? { stopIfTrue: rule.stopIfTrue } : {}),
    stops: rule.stops.map(({ type, value, color }) => ({
      cfvo: { type, ...(value !== undefined ? { value } : {}) },
      color,
    })),
  }
}
