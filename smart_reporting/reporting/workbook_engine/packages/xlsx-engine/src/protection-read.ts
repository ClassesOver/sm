/// Protection state readback (本地新增): the editor projects whether a sheet or
/// the workbook structure is protected, and whether a password guards it, so
/// the protect/unprotect commands only offer what `protection.ts` can write
/// (no password support: password-protected targets stay as they are).

import { readXmlAttribute } from './xml'

export interface SheetProtectionModel {
  readonly protected: boolean
  readonly hasPassword: boolean
}

export interface WorkbookProtectionModel {
  readonly lockStructure: boolean
  readonly hasPassword: boolean
}

const truthy = (value: string | undefined) => value === '1' || value === 'true'

export function readSheetProtection(worksheetXml: string): SheetProtectionModel | undefined {
  const element = worksheetXml.match(/<(?:\w+:)?sheetProtection\b[^>]*>/)?.[0]
  if (!element) return undefined
  return {
    protected: truthy(readXmlAttribute(element, 'sheet')),
    hasPassword: /\b(?:password|hashValue)="/.test(element),
  }
}

export function readWorkbookProtection(workbookXml: string): WorkbookProtectionModel | undefined {
  const element = workbookXml.match(/<(?:\w+:)?workbookProtection\b[^>]*>/)?.[0]
  if (!element) return undefined
  return {
    lockStructure: truthy(readXmlAttribute(element, 'lockStructure')),
    hasPassword: /\bworkbook(?:Password|HashValue)="/.test(element),
  }
}
