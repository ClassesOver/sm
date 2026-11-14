import type { NativeOperation } from './native-draft'
import type { DocxProtectionModel } from './docx-protection'

function assertEditable(model: DocxProtectionModel | null): asserts model is DocxProtectionModel {
  if (!model || !model.editable || model.contentLocked || model.protection?.enforced || !/^[a-f0-9]{64}$/.test(model.expectedSettingsSha256)) throw Error(model?.readOnlyReason ?? '当前来源不支持修改对称页边距')
}

/** Select and validate the document-global flag from the existing native operation journal. */
export function docxMirrorMarginsOperations(operations: NativeOperation[], model: DocxProtectionModel | null): NativeOperation[] {
  const selected = operations.filter(operation => operation.kind === 'setMirrorMargins')
  if (!selected.length) return []
  assertEditable(model)
  if (selected.length !== 1) throw Error('对称页边距草稿包含重复操作')
  const operation = selected[0]!
  if (Object.keys(operation).sort().join() !== 'enabled,expectedSettingsSha256,kind' || typeof operation.enabled !== 'boolean') throw Error('对称页边距草稿无效')
  if (operation.expectedSettingsSha256 !== model.expectedSettingsSha256) throw Error('对称页边距草稿与当前来源不一致')
  return [{ ...operation }]
}

/** Compose with section layout before one nativeDocxOperations history transaction.
 * Returning to the original parsed flag removes the pending operation entirely.
 */
export function withDocxMirrorMargins(operations: NativeOperation[], model: DocxProtectionModel | null, enabled: boolean, sourceEnabled: boolean): NativeOperation[] {
  assertEditable(model)
  if (typeof enabled !== 'boolean' || typeof sourceEnabled !== 'boolean') throw Error('对称页边距值无效')
  docxMirrorMarginsOperations(operations, model)
  const others = operations.filter(operation => operation.kind !== 'setMirrorMargins')
  return enabled === sourceEnabled ? others : [...others, { kind: 'setMirrorMargins', expectedSettingsSha256: model.expectedSettingsSha256, enabled }]
}

/** A derived value only: native history and recovery remain the single source of draft state. */
export function currentDocxMirrorMargins(operations: NativeOperation[], model: DocxProtectionModel | null, sourceEnabled: boolean): boolean {
  const operation = docxMirrorMarginsOperations(operations, model)[0]
  return operation ? operation.enabled as boolean : sourceEnabled
}
