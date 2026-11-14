import {expect,it} from 'vitest'
import {inspectDocxProtection} from '../../../reporting/doc_engine/bridge/docx-protection'
import {docxDocumentToolModels,docxDocumentToolOperations} from './docx-document-tools'
it('rejects body drafts for unsupported write-protection sources before they can enter the journal',()=>{
 const settings='<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:writeProtection w:recommended="1"/></w:settings>'
 const models=docxDocumentToolModels({documentProtection:inspectDocxProtection(settings)})
 expect(models.protection?.contentLocked).toBe(true)
 expect(()=>docxDocumentToolOperations([{kind:'replaceParagraph',blockId:'p',text:'overwrite'}],models)).toThrow('只读')
 expect(docxDocumentToolOperations([],models)).toEqual([])
})
