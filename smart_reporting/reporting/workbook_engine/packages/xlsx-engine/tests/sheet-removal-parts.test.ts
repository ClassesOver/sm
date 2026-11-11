import { expect, it } from 'vitest'
const implementation = '../src/sheet-removal-parts'
const packageNs = 'http://schemas.openxmlformats.org/package/2006/relationships', office = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
const rels = (entries: string) => `<Relationships xmlns="${packageNs}">${entries}</Relationships>`
const link = (id: string, type: string, target: string, mode = '') => `<Relationship Id="${id}" Type="${office}${type}" Target="${target}"${mode ? ` TargetMode="${mode}"` : ''}/>`
const source = (entries: Record<string, string>) => ({ paths: async () => Object.keys(entries), has: async (path: string) => path in entries, readText: async (path: string) => { if (!(path in entries)) throw Error('missing');return entries[path]! } })
const base = () => ({ 'xl/worksheets/a.xml': '', 'xl/worksheets/b.xml': '', 'xl/worksheets/_rels/a.xml.rels': rels(link('d','drawing','../drawings/d.xml')), 'xl/drawings/d.xml':'', 'xl/drawings/_rels/d.xml.rels': rels(link('c','chart','../charts/c.xml')+link('i','image','../media/i.png')), 'xl/charts/c.xml':'', 'xl/media/i.png':'' })
it('plans exclusive owned satellites and relationship parts without deleting sheet roots', async () => {
 const { planSheetRemovalParts } = await import(/* @vite-ignore */ implementation)
 expect([...(await planSheetRemovalParts(source(base()), ['xl/worksheets/a.xml'])).removedParts].sort()).toEqual(['xl/charts/c.xml','xl/drawings/_rels/d.xml.rels','xl/drawings/d.xml','xl/media/i.png'])
})
it('pulls shared targets and their complete internal subtrees back into the surviving package', async () => {
 const { planSheetRemovalParts } = await import(/* @vite-ignore */ implementation)
 const entries = {...base(),'xl/worksheets/_rels/b.xml.rels':rels(link('d','drawing','../drawings/d.xml'))}
 expect([...(await planSheetRemovalParts(source(entries), ['xl/worksheets/a.xml'])).removedParts]).toEqual([])
 entries['xl/worksheets/_rels/b.xml.rels']=rels(link('i','image','../media/i.png'))
 expect([...(await planSheetRemovalParts(source(entries), ['xl/worksheets/a.xml'])).removedParts].sort()).toEqual(['xl/charts/c.xml','xl/drawings/_rels/d.xml.rels','xl/drawings/d.xml'])
})
it('handles cycles, multiple removed owners and external links without following remote targets', async () => {
 const { planSheetRemovalParts } = await import(/* @vite-ignore */ implementation)
 const entries={...base(),'xl/worksheets/_rels/b.xml.rels':rels(link('d','drawing','../drawings/d.xml')),'xl/charts/_rels/c.xml.rels':rels(link('cycle','chart','../drawings/d.xml')+link('remote','image','https://example.test/a.png','External'))}
 expect((await planSheetRemovalParts(source(entries), ['xl/worksheets/a.xml','xl/worksheets/b.xml'])).removedParts.size).toBe(5)
})
it.each([
 ['unknown root',rels(link('x','pivotTable','../drawings/d.xml'))],
 ['foreign type',rels('<Relationship Id="x" Type="urn:foreign/drawing" Target="../drawings/d.xml"/>')],
 ['foreign namespace','<Relationships xmlns="urn:foreign"><Relationship Id="x" Type="drawing" Target="d"/></Relationships>'],
 ['invalid mode',rels(link('d','drawing','../drawings/d.xml','Weird'))],
 ['root escape',rels(link('d','drawing','../../../evil.xml'))],
 ['uri internal',rels(link('d','drawing','https://example.test/d.xml'))],
 ['missing part',rels(link('d','drawing','../drawings/missing.xml'))],
 ['malformed',`<Relationships xmlns="${packageNs}"><Relationship></Relationships>`],
])('rejects incomplete or unsafe ownership: %s', async (_label, xml) => {
 const { planSheetRemovalParts } = await import(/* @vite-ignore */ implementation)
 await expect(planSheetRemovalParts(source({...base(),'xl/worksheets/_rels/a.xml.rels':xml}), ['xl/worksheets/a.xml'])).rejects.toThrow()
})
it('accepts legal alias namespaces and encoded normalized internal targets', async () => {
 const { planSheetRemovalParts } = await import(/* @vite-ignore */ implementation)
 const entries={...base(),'xl/worksheets/_rels/a.xml.rels':`<p:Relationships xmlns:p="${packageNs}"><p:Relationship Id="d" Type="${office}drawing" Target="/xl/drawings/%64.xml"/></p:Relationships>`}
 expect((await planSheetRemovalParts(source(entries), ['xl/worksheets/a.xml'])).removedParts.size).toBe(4)
})
it('removes only deleted-part overrides and preserves defaults and other XML bytes', async () => {
 const { removePartOverrides } = await import(/* @vite-ignore */ implementation)
 const xml='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="png" ContentType="image/png"/><Override PartName="/xl/drawings/d.xml" ContentType="drawing"/><Override PartName="/xl/charts/c.xml" ContentType="chart"/></Types>'
 expect(removePartOverrides(xml,new Set(['xl/drawings/d.xml']))).toBe(xml.replace('<Override PartName="/xl/drawings/d.xml" ContentType="drawing"/>',''))
})
it('accepts strict relationship URI roots and retains targets from package-level incoming relationships', async () => {
 const { planSheetRemovalParts } = await import(/* @vite-ignore */ implementation)
 const entries={...base(),'xl/worksheets/_rels/a.xml.rels':rels('<Relationship Id="d" Type="http://purl.oclc.org/ooxml/officeDocument/relationships/drawing" Target="../drawings/d.xml"/>'),'_rels/.rels':rels('<Relationship Id="shared" Type="urn:unknown-surviving" Target="xl/drawings/d.xml"/>')}
 expect((await planSheetRemovalParts(source(entries), ['xl/worksheets/a.xml'])).removedParts.size).toBe(0)
})
it.each([
 rels(link('d','drawing','../drawings/d.xml')+link('d','drawing','../drawings/d.xml')),
 rels(link('d','drawing','%2f%2fevil/d.xml')),
 rels(link('d','drawing','../drawings/%00.xml')),
 rels(link('d','drawing','../drawings/%ZZ.xml')),
 '<!DOCTYPE Relationships><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
])('rejects ambiguous identities and unsafe encoded targets %#', async xml => {
 const { planSheetRemovalParts } = await import(/* @vite-ignore */ implementation)
 await expect(planSheetRemovalParts(source({...base(),'xl/worksheets/_rels/a.xml.rels':xml}), ['xl/worksheets/a.xml'])).rejects.toThrow()
})
it('removes prefixed paired overrides without touching unrelated bytes and rejects foreign namespace lookalikes', async () => {
 const { removePartOverrides } = await import(/* @vite-ignore */ implementation)
 const node='<c:Override PartName="/xl/drawings/d.xml" ContentType="drawing"></c:Override>', xml=`<c:Types xmlns:c="http://schemas.openxmlformats.org/package/2006/content-types">${node}<c:Default Extension="png" ContentType="image/png"/></c:Types>`
 expect(removePartOverrides(xml,new Set(['xl/drawings/d.xml']))).toBe(xml.replace(node,''))
 expect(() => removePartOverrides('<Types xmlns="urn:foreign"><Override PartName="/xl/drawings/d.xml"/></Types>',new Set(['xl/drawings/d.xml']))).toThrow('命名空间')
})
