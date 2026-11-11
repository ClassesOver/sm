import { afterEach, expect, it, vi } from 'vitest'
import { createBlankWorkbook, assemblePackage } from '@sheets-web/xlsx-engine'
const readerPath='./workbook-queries-reader',controllerPath='./workbook-queries'
const reader=()=>import(/* @vite-ignore */ readerPath),controller=()=>import(/* @vite-ignore */ controllerPath)
const ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main',rels='http://schemas.openxmlformats.org/package/2006/relationships',office='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
async function fixture(extra:Record<string,string>={}) {
 const source=await createBlankWorkbook("Bob's Data"),parts=new Map<string,string>()
 const zip={file:(path:string,text:string)=>parts.set(path,text)}
 zip.file('xl/connections.xml',`<connections xmlns="${ns}"><connection id="1" name="Web"><webPr url="https://user:password@example.com/data?token=secret#private"/></connection><connection id="2" name="Text"><textPr sourceFile="C:/private/values.csv"/></connection><connection id="3" name="Database"><dbPr connection="Provider=SQL;Password=db-secret;User ID=admin" command="SELECT secret FROM private"/></connection><connection id="4" name="Query - Rates"><dbPr connection="Provider=Microsoft.Mashup.OleDb.1;Location=Rates;Password=pq-secret"/></connection><connection id="5" name="Only"/></connections>`)
 zip.file('xl/_rels/workbook.xml.rels',`<Relationships xmlns="${rels}"><Relationship Id="rId1" Type="${office}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>`)
 zip.file('xl/workbook.xml',`<workbook xmlns="${ns}" xmlns:r="${office}"><sheets><sheet name="Bob&apos;s Data" sheetId="1" r:id="rId1"/></sheets><definedNames><definedName name="ExternalData_1" localSheetId="0">'Bob''s Data'!$D$4:$E$9</definedName></definedNames></workbook>`)
 zip.file('xl/worksheets/_rels/sheet1.xml.rels',`<Relationships xmlns="${rels}"><Relationship Id="t" Type="${office}/table" Target="../tables/table1.xml"/><Relationship Id="q" Type="${office}/queryTable" Target="../queryTables/queryTable2.xml"/><Relationship Id="external" Type="${office}/table" Target="https://evil.example/leak" TargetMode="External"/></Relationships>`)
 zip.file('xl/tables/table1.xml',`<table xmlns="${ns}" name="Loaded" displayName="Loaded" ref="A1:B6" headerRowCount="1" totalsRowCount="1"/>`)
 zip.file('xl/tables/_rels/table1.xml.rels',`<Relationships xmlns="${rels}"><Relationship Id="q" Type="${office}/queryTable" Target="../queryTables/queryTable1.xml"/></Relationships>`)
 zip.file('xl/queryTables/queryTable1.xml',`<queryTable xmlns="${ns}" name="Loaded" connectionId="1"/>`)
 zip.file('xl/queryTables/queryTable2.xml',`<queryTable xmlns="${ns}" name="ExternalData_1" connectionId="2" headers="0"/>`)
 for(const [path,xml]of Object.entries(extra))zip.file(path,xml)
 return (await assemblePackage(source,{replaced:parts,added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[]})).buffer
}
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();document.body.replaceChildren()})
it('reads real workbook connection types, loaded table and legacy named destinations',async()=>{
 const {readWorkbookQueries}=await reader(),bytes=await fixture(),fetch=vi.fn();vi.stubGlobal('fetch',fetch)
 const result=await readWorkbookQueries(bytes)
 expect(result.map((q:any)=>[q.name,q.kind])).toEqual([['Web','web'],['Text','text'],['Database','database'],['Rates','powerQuery'],['Only','other']])
 expect(result[0].destination).toEqual({sheet:"Bob's Data",table:'Loaded',hasTable:true,range:'A1:B6',headerRows:1,totalsRows:1,rows:4})
 expect(result[1].destination).toEqual({sheet:"Bob's Data",hasTable:false,range:'D4:E9',headerRows:0,totalsRows:0,rows:6})
 expect(result[0].source).toBe('https://example.com/data');expect(result[1].source).toBe('values.csv');expect(fetch).not.toHaveBeenCalled()
 expect(JSON.stringify(result)).not.toMatch(/password|secret|SELECT|User ID|admin|token|private/i)
})
it('distinguishes a real empty workbook from damaged XML',async()=>{
 const {readWorkbookQueries}=await reader();expect(await readWorkbookQueries(await createBlankWorkbook())).toEqual([])
 await expect(readWorkbookQueries(await fixture({'xl/connections.xml':'<connections><connection id="1"></connections>'}))).rejects.toThrow()
 await expect(readWorkbookQueries(await fixture({'xl/connections.xml':'<!DOCTYPE connections [<!ENTITY e SYSTEM "file:///secret">]><connections/>'}))).rejects.toThrow()
})
it('does not expose credentials hidden in descriptions or external relationship targets',async()=>{
 const {readWorkbookQueries}=await reader(),result=await readWorkbookQueries(await fixture({'xl/connections.xml':`<connections xmlns="${ns}"><connection id="1" name="Safe" description="Password=description-secret;Token=hidden;note=ok"><webPr url="javascript:alert(document.cookie)"/></connection></connections>`}))
 expect(result[0].source).toBeUndefined();expect(JSON.stringify(result)).not.toMatch(/description-secret|hidden|javascript|document.cookie/)
})
it('does not invent queries from comments and rejects a wrong namespace or out-of-grid destination',async()=>{
 const {readWorkbookQueries}=await reader()
 expect(await readWorkbookQueries(await fixture({'xl/connections.xml':`<connections xmlns="${ns}"><!-- <connection id="1" name="Fake"/> --></connections>`}))).toEqual([])
 await expect(readWorkbookQueries(await fixture({'xl/connections.xml':'<connections xmlns="urn:foreign"><connection id="1" name="Fake"/></connections>'}))).rejects.toThrow()
 const result=await readWorkbookQueries(await fixture({'xl/tables/table1.xml':`<table xmlns="${ns}" name="Bad" ref="A0:ZZZ9999999"/>`}))
 expect(result[0].destination).toBeUndefined()
})
it('does not project free-form descriptions or credentials inside connection names',async()=>{
 const {readWorkbookQueries}=await reader(),result=await readWorkbookQueries(await fixture({'xl/connections.xml':`<connections xmlns="${ns}"><connection id="1" name="Rates UID=alice;Endpoint=https://alice:my-secret@example.com/db" description="Server=sql;UID=alice;Endpoint=https://alice:description-secret@example.com/db"><dbPr connection="Server=sql;Password=db-secret"/></connection></connections>`}))
 expect(result[0].description).toBeUndefined();expect(result[0].name).toContain('Rates');expect(JSON.stringify(result)).not.toMatch(/alice|my-secret|description-secret|db-secret/)
})
it('only projects connection and destination elements in their real OOXML parent paths',async()=>{
 const {readWorkbookQueries}=await reader()
 expect(await readWorkbookQueries(await fixture({'xl/connections.xml':`<connections xmlns="${ns}"><extLst><ext uri="foreign"><connection id="9" name="Nested fake"><webPr url="https://example.com"/></connection></ext></extLst></connections>`}))).toEqual([])
 const result=await readWorkbookQueries(await fixture({'xl/tables/_rels/table1.xml.rels':`<Relationships xmlns="${rels}"><ext><Relationship Id="q" Type="${office}/queryTable" Target="../queryTables/queryTable1.xml"/></ext></Relationships>`}))
 expect(result[0].destination).toBeUndefined()
})
it('shows source metadata and navigates only loaded destinations with quoted sheet names',async()=>{
 const {createWorkbookQueriesDialog}=await controller(),book={},onGo=vi.fn(()=>null),getBytes=vi.fn(async()=>fixture())
 const dialog=createWorkbookQueriesDialog(document.body,{getWorkbook:()=>book,getBytes,onGo});await dialog.open()
 const modal=document.querySelector<HTMLElement>('[role=dialog]')!;expect(modal.hidden).toBe(false);expect(modal.textContent).toContain('Power Query');expect(modal.textContent).toContain('只读');expect(modal.querySelectorAll('[data-query-entry]')).toHaveLength(5)
 expect(modal.querySelector<HTMLButtonElement>('[data-query-entry="2"]')!.disabled).toBe(true);modal.querySelector<HTMLButtonElement>('[data-query-entry="0"]')!.click();await vi.waitFor(()=>expect(onGo).toHaveBeenCalledWith("'Bob''s Data'!A1:B6"));expect(modal.hidden).toBe(true);dialog.dispose()
})
it('shows true empty and damaged-load states without fabricating successful empty data',async()=>{
 const {createWorkbookQueriesDialog}=await controller(),book={};let bytes=await createBlankWorkbook()
 const dialog=createWorkbookQueriesDialog(document.body,{getWorkbook:()=>book,getBytes:()=>bytes,onGo:()=>null});await dialog.open();expect(document.body.textContent).toContain('没有查询或数据连接');dialog.close()
 bytes=await fixture({'xl/connections.xml':'<broken'});await dialog.open();expect(document.querySelector('[role=alert]')?.textContent).toContain('无法读取');expect(document.querySelector('[data-query-empty]')?.hasAttribute('hidden')).toBe(true);dialog.dispose()
})
it.each(['close','replacement','blocked','dispose'])('drops late load after %s',async mode=>{
 const {createWorkbookQueriesDialog}=await controller();let book={},blocked=false,resolve!:(value:Uint8Array)=>void
 const dialog=createWorkbookQueriesDialog(document.body,{getWorkbook:()=>book,getBytes:()=>new Promise<Uint8Array>(r=>{resolve=r}),onGo:()=>null,isBlocked:()=>blocked}),loading=dialog.open()
 if(mode==='close')dialog.close();if(mode==='replacement')book={};if(mode==='blocked')blocked=true;if(mode==='dispose')dialog.dispose()
 resolve(await fixture());await loading;expect(document.querySelectorAll('[data-query-entry]')).toHaveLength(0);if(mode!=='dispose')dialog.dispose()
})
it('refuses navigation when blocked or workbook replaced, and shows specific navigation errors',async()=>{
 const {createWorkbookQueriesDialog}=await controller();let book={},blocked=false;const onGo=vi.fn(()=> '目标工作表已删除')
 const dialog=createWorkbookQueriesDialog(document.body,{getWorkbook:()=>book,getBytes:()=>fixture(),onGo,isBlocked:()=>blocked});await dialog.open()
 const click=()=>document.querySelector<HTMLButtonElement>('[data-query-entry="0"]')!.click();click();await vi.waitFor(()=>expect(document.querySelector('[role=alert]')?.textContent).toContain('目标工作表已删除'))
 blocked=true;click();expect(onGo).toHaveBeenCalledTimes(1);blocked=false;book={};click();expect(onGo).toHaveBeenCalledTimes(1);dialog.dispose()
})
