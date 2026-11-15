import type { DocxProtectionModel } from './docx-protection'

/** Validate only the setMirrorMargins subset of a revision-bound native operation batch.
 * The caller validates the full batch, registered revision identity and protection first.
 * An absent operation leaves settings untouched; false explicitly removes the source flag.
 */
export function validateDocxMirrorMarginsOperations(operations: Record<string, unknown>[], model: DocxProtectionModel): boolean | undefined {
  if (!operations.length) return undefined
  if (operations.length !== 1) throw Error('docx_mirror_margins_duplicate')
  const operation = operations[0]!
  if (operation.kind !== 'setMirrorMargins' || Object.keys(operation).sort().join() !== 'enabled,expectedSettingsSha256,kind' || typeof operation.enabled !== 'boolean') throw Error('docx_mirror_margins_operation_invalid')
  if (!model.editable || model.contentLocked || model.protection?.enforced) throw Error('docx_mirror_margins_source_readonly')
  if (!/^[a-f0-9]{64}$/.test(model.expectedSettingsSha256) || operation.expectedSettingsSha256 !== model.expectedSettingsSha256) throw Error('docx_mirror_margins_anchor_invalid')
  return operation.enabled
}
