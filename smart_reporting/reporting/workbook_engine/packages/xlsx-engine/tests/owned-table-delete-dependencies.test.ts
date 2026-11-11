import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'
import { createBufferEntrySource } from '../src/zip'
const implementation = '../src/sheet-removal-parts'
function fixture(reference: string, scope = '') {
 return new Uint8Array(execFileSync(fileURLToPath(new URL('../../../../../../.venv/bin/python', import.meta.url)), ['-c', `
from io import BytesIO
import sys
from openpyxl import Workbook
from openpyxl.worksheet.table import Table
from openpyxl.workbook.defined_name import DefinedName
b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other');s.append(['Amount']);s.append([1]);s.append([2]);s.add_table(Table(displayName='SalesData',ref='A1:A3'));other['B1']=99
ref=${JSON.stringify(reference)};scope=${JSON.stringify(scope)}
if scope:
 n=DefinedName('TableDependency',attr_text=ref)
 if scope=='global':b.defined_names.add(n)
 else:b[scope].defined_names.add(n)
elif ref:other['A1']='='+ref
f=BytesIO();b.save(f);sys.stdout.buffer.write(f.getvalue())
`]))
}
it('rejects a real surviving worksheet structured reference case-insensitively', async () => {
 const module = await import(/* @vite-ignore */ implementation), source = await createBufferEntrySource(fixture('SUM(salesdata[Amount])'))
 const { removedParts } = await module.planSheetRemovalParts(source,['xl/worksheets/sheet1.xml'])
 await expect(module.assertRemovedTableDependencies(source,removedParts,['xl/worksheets/sheet2.xml'],await source.readText('xl/workbook.xml'),new Set([0]))).rejects.toThrow('SalesData')
})
it.each(['global','Other'])('rejects a surviving %s name structured reference', async scope => {
 const module = await import(/* @vite-ignore */ implementation), source = await createBufferEntrySource(fixture('SUM(SALESDATA[Amount])',scope))
 const { removedParts } = await module.planSheetRemovalParts(source,['xl/worksheets/sheet1.xml'])
 await expect(module.assertRemovedTableDependencies(source,removedParts,['xl/worksheets/sheet2.xml'],await source.readText('xl/workbook.xml'),new Set([0]))).rejects.toThrow('SalesData')
})
it.each([['SUM(SalesData[Amount])','Source'],['',''],['SUM(OtherData[Amount])','global']])('allows no surviving dependency: %s scope %s', async (reference,scope) => {
 const module = await import(/* @vite-ignore */ implementation), source = await createBufferEntrySource(fixture(reference,scope))
 const { removedParts } = await module.planSheetRemovalParts(source,['xl/worksheets/sheet1.xml'])
 await expect(module.assertRemovedTableDependencies(source,removedParts,['xl/worksheets/sheet2.xml'],await source.readText('xl/workbook.xml'),new Set([0]))).resolves.toBeUndefined()
})
it('does not reject a table retained through a surviving relationship', async () => {
 const module = await import(/* @vite-ignore */ implementation), source = await createBufferEntrySource(fixture('SUM(SalesData[Amount])'))
 await expect(module.assertRemovedTableDependencies(source,new Set(),['xl/worksheets/sheet2.xml'],await source.readText('xl/workbook.xml'),new Set([0]))).resolves.toBeUndefined()
})

it('rejects the actual applySheetEdits save chain before removing a table used by another sheet', async () => {
 const { applySheetEdits } = await import('../src/sheet-ops')
 await expect(applySheetEdits(fixture('SUM(SalesData[Amount])'),{ renames: [], additions: [], removals: ['Source'], order: ['Other'] })).rejects.toThrow('SalesData')
})
