import type { SectionInfo, HfPartInfo } from '@genoffice/docx-engine'
import type { NativeOperation } from './native-draft'
import type { DocxSectionAnchor } from './docx-operations'
import { restoredDocxHeaderFooterOperations, type DocxHfPart, type DocxHfVariant, type DocxHfPartAnchor, type DocxHeadersFootersModel } from './docx-hf'
import { editKey, resolveHf, withHfLink, type HfSectionState } from './vendor/genoffice-docs/apps/docs/src/renderer/hf-sections'

export interface SectionHfPartAnchor extends DocxHfPartAnchor {
  relationshipsSha256: string | null; ownRelationshipsSha256: string | null;
  ownRId: string | null; ownPath: string | null; ownPartSha256: string
  ownerSectionId: string; path: string | null; linked: boolean | null; readOnlyReason?: string
}
export interface SectionHfModel { parts: Partial<Record<`${DocxHfPart}.${DocxHfVariant}`, SectionHfPartAnchor>> }
const LINK_KEYS = ['kind', 'sectionId', 'expectedSectionSha256', 'part', 'variant', 'linked', 'expectedOwnRId', 'expectedOwnPartSha256', 'expectedOwnerSectionId', 'expectedRId', 'expectedPartSha256', 'expectedRelationshipsSha256', 'expectedOwnRelationshipsSha256']
export function sectionHfLinkOperation(section: DocxSectionAnchor, part: DocxHfPart, variant: DocxHfVariant, linked: boolean): NativeOperation {
  const found = section.headersFooters?.parts[`${part}.${variant}`]
  if (!found) throw new Error('页眉页脚部件身份缺失')
  return { kind: 'setHeaderFooterLink', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256,
    part, variant, linked, expectedOwnRId: found.ownRId, expectedOwnPartSha256: found.ownPartSha256,
    expectedOwnerSectionId: found.ownerSectionId, expectedRId: found.rId, expectedPartSha256: found.expectedPartSha256,
    expectedRelationshipsSha256: found.relationshipsSha256, expectedOwnRelationshipsSha256: found.ownRelationshipsSha256 }
}
/** 按整批链接计划解析有效owner及其原快照来源（新own尚无rId，仍能核验复制来源）。 */
export function plannedSectionHfTarget(sections: readonly DocxSectionAnchor[], operations: NativeOperation[], index: number, part: DocxHfPart, variant: DocxHfVariant) {
  let result: { owner: number; anchor: SectionHfPartAnchor } | undefined
  for (let current = 0; current <= index; current++) {
    const section = sections[current]!, source = section.headersFooters?.parts[`${part}.${variant}`]
    if (!source) throw new Error('草稿页眉页脚部件身份缺失')
    const link = operations.find(operation => operation.kind === 'setHeaderFooterLink' && operation.sectionId === section.sectionId && operation.part === part && operation.variant === variant)
    if (link?.linked === true || !source.ownRId && link?.linked !== false) result ??= { owner: current, anchor: source }
    else if (link?.linked === false && source.linked) result = { owner: current, anchor: result?.anchor ?? source }
    else result = { owner: current, anchor: source }
  }
  return result!
}
export function restoredSectionHfOperations(operations: NativeOperation[], sections: readonly DocxSectionAnchor[]): NativeOperation[] {
  const kept: NativeOperation[] = []
  for (const operation of operations) {
    if (operation.kind !== 'setHeaderFooter' && operation.kind !== 'setHeaderFooterLink') continue
    const index = sections.findIndex(section => section.sectionId === operation.sectionId), section = sections[index]
    if (!section || section.expectedSectionSha256 !== operation.expectedSectionSha256) throw new Error('草稿页眉页脚节身份不一致')
    const part = operation.part as DocxHfPart, variant = operation.variant as DocxHfVariant
    if (!['header', 'footer'].includes(part) || !['default', 'first', 'even'].includes(variant)) throw new Error('草稿页眉页脚部件无效')
    const found = section.headersFooters?.parts[`${part}.${variant}`]
    if (!found) throw new Error('草稿页眉页脚部件身份缺失')
    if (operation.kind === 'setHeaderFooterLink') {
      if (!index || !found.editable || typeof operation.linked !== 'boolean' || Object.keys(operation).some(key => !LINK_KEYS.includes(key))) throw new Error('草稿链接前一节不可用')
      const expected = sectionHfLinkOperation(section, part, variant, operation.linked)
      if (LINK_KEYS.some(key => operation[key] !== expected[key])) throw new Error('草稿页眉页脚链接身份不一致')
      if (kept.some(item => item.kind === operation.kind && item.sectionId === section.sectionId && item.part === part && item.variant === variant)) throw new Error('草稿页眉页脚链接重复')
      kept.push(operation)
    } else {
      const link = operations.find(item => item.kind === 'setHeaderFooterLink' && item.sectionId === section.sectionId && item.part === part && item.variant === variant)
      let source = found
      if (operation.afterLink !== undefined) {
        if (operation.afterLink !== true || link?.linked !== false || !found.linked) throw new Error('草稿解除链接后编辑须匹配本节的解除链接操作')
        const planned = plannedSectionHfTarget(sections, operations, index, part, variant)
        if (planned.owner !== index || !planned.anchor.editable) throw new Error('草稿解除链接后来源身份无法核验')
        source = planned.anchor
      } else if (link) throw new Error('草稿链接变更后的内容操作身份不一致')
      const model = { titlePg: section.titlePg, evenAndOddHeaders: false, pageNumberFmt: section.pageNumberFmt, pageNumberStart: section.pageNumberStart, parts: { ...section.headersFooters?.parts, [`${part}.${variant}`]: source } } as DocxHeadersFootersModel
      kept.push(...restoredDocxHeaderFooterOperations([operation], section, model))
    }
  }
  const effective = new Map<string, SectionHfPartAnchor>()
  for (const section of sections) for (const [key, source] of Object.entries(section.headersFooters?.parts ?? {})) {
    const link = kept.find(operation => operation.kind === 'setHeaderFooterLink' && operation.sectionId === section.sectionId && `${operation.part}.${operation.variant}` === key)
    const prior = effective.get(key)
    if (link?.linked === false && source.linked && prior && !prior.editable) throw new Error('继承部件包含复杂关系，当前无法完整复制，保留原文件设置')
    effective.set(key, link?.linked === true || source.linked && link?.linked !== false ? prior ?? source : source)
  }
  if (kept.some(operation => operation.kind === 'setHeaderFooterLink') && operations.some(operation => operation.kind === 'insertSectionBreak')) throw new Error('分节符变更尚未保存，请先保存后切换页眉页脚链接')
  return kept
}

/** 官方继承模型负责草稿中的有效owner及内容；来源身份始终来自inspect快照。 */
export function sectionHfState(sections: SectionInfo[], anchors: readonly DocxSectionAnchor[], operations: NativeOperation[], parts?: Record<string, HfPartInfo>): HfSectionState {
  let state: HfSectionState = { sections, edits: {}, links: {}, parsed: { hfParts: parts } }
  const applyContent = (operation: NativeOperation) => {
    const index = anchors.findIndex(section => section.sectionId === operation.sectionId)
    const align = operation.align as 'left' | 'center' | 'right' | undefined
    state.edits[editKey(sections[index]!.lastBlockIndex, operation.part as DocxHfPart, operation.variant as DocxHfVariant)] = {
      text: operation.text as string, pageNumber: operation.pageNumber as boolean,
      paras: (operation.text as string).split('\n').map(text => ({ ...(align ? { align } : {}), runs: [{ text }] })),
    }
  }
  for (const operation of operations) if (operation.kind === 'setHeaderFooter' && !operation.afterLink) applyContent(operation)
  for (const [index, anchor] of anchors.entries()) for (const operation of operations) {
    if (operation.kind !== 'setHeaderFooterLink' || operation.sectionId !== anchor.sectionId) continue
    const pending = withHfLink(state, index, operation.part as DocxHfPart, operation.variant as DocxHfVariant, operation.linked as boolean)
    if (pending) state = { ...state, ...pending }
  }
  for (const operation of operations) if (operation.kind === 'setHeaderFooter' && operation.afterLink) applyContent(operation)
  return state
}

export { resolveHf, withHfLink }
