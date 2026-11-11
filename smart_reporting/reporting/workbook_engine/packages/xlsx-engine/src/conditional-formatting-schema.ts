/** Native Univer full-rule wire validation; the fixed source serializer defines representability. */
import { z } from 'zod'
import { cfRuleUnsaveableReason } from './conditional-formatting-source'
const area=z.object({
 startRow:z.number().int().min(0).max(1048575),endRow:z.number().int().min(0).max(1048575),
 startColumn:z.number().int().min(0).max(16383),endColumn:z.number().int().min(0).max(16383),
}).strict().refine(value=>value.startRow<=value.endRow&&value.startColumn<=value.endColumn,'Conditional-formatting ranges must be ordered.')
export const conditionalFormattingSnapshotRuleSchema=z.object({
 ranges:z.array(area).min(1).max(10000),stopIfTrue:z.boolean(),rule:z.record(z.string(),z.unknown()),
}).strict().superRefine((wire,context)=>{
 const reason=cfRuleUnsaveableReason(wire.rule)
 if(reason!==null)context.addIssue({code:'custom',path:['rule'],message:reason})
})
export const replaceSheetConditionalFormatsOperationSchema=z.object({
 kind:z.literal('replaceSheetConditionalFormats'),sheetName:z.string().min(1).max(31),rules:z.array(conditionalFormattingSnapshotRuleSchema).max(10000),
}).strict()
