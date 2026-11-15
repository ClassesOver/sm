/** Validation only: the ordinary insertParagraph writer preserves the original table XML. */
export function validateTableTailParagraph(op: Record<string, unknown>, block: {type:string;originalXml?:string;sdtShell?:unknown}, blockId:string, expectedObjectSha256:string, protectedDocument:boolean):string {
 const fail=():never=>{throw new Error('table_tail_paragraph_invalid')}
 if(protectedDocument||block.type!=='table'||!block.originalXml||block.sdtShell||!/^<w:tbl[\s>]/.test(block.originalXml)
  ||op.kind!=='insertParagraph'||op.position!=='after'||op.blockId!==blockId||op.expectedObjectSha256!==expectedObjectSha256
  ||Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','position','text'].includes(k)))fail()
 if(typeof op.text!=='string'||op.text.length>20000||/[\x00-\x08\x0b-\x1f]/.test(op.text))fail()
 return op.text as string
}
