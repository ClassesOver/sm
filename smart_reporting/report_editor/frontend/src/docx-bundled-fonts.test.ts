import {loadDocxBundledFonts} from './docx-bundled-fonts'
import wordFaces from './vendor/genoffice-docs/packages/font-metrics/word-faces.json'
import {afterEach,expect,it,vi} from 'vitest'
import {resolveDeclaredFace,setFontMetricsProvider,setResolverEmbeddedFaces,setBrowserFontMetrics,browserFontFace} from './vendor/genoffice-docs/apps/docs/src/renderer/font-resolve'
import {lineHeightFactor,latinLineFactor,cjkDeclaredLineFactor} from './vendor/genoffice-docs/apps/docs/src/renderer/line-metrics'
import {runFaceDecls} from './vendor/genoffice-docs/apps/docs/src/renderer/text-layout/run-faces'

afterEach(()=>{setFontMetricsProvider(undefined);setResolverEmbeddedFaces([]);setBrowserFontMetrics([]);vi.unstubAllGlobals()})
it('renders selected built-in Chinese face directly while retaining the Latin slot',async()=>{
 vi.stubGlobal('document',{fonts:{load:vi.fn().mockResolvedValue([{}])}})
 await loadDocxBundledFonts()
 const attrs={font:'Noto Sans CJK SC',eastAsiaFont:'Noto Sans CJK SC',fontAscii:'Noto Serif CJK SC'}
 expect(runFaceDecls(attrs,null).decls.find(value=>value.startsWith('--doc-east-asian-font:'))).toContain("'KR Theme Latin GO','Noto Sans CJK SC'")
 expect(attrs.fontAscii).toBe('Noto Serif CJK SC')
 expect(browserFontFace('Noto Sans CJK SC')).toMatchObject({family:'noto sans cjk sc',eastAsian:true})
})

it('preserves source metrics and snapshot-only faces outside the registered assets',async()=>{
 const names=['Arial','Caladea',...Object.keys(wordFaces.system).filter(key=>!wordFaces.faces[key as keyof typeof wordFaces.faces]).slice(0,8)]
 const before=names.map(name=>resolveDeclaredFace(name))
 vi.stubGlobal('document',{fonts:{load:vi.fn().mockResolvedValue([{}])}})
 await loadDocxBundledFonts()
 expect(names.map(name=>resolveDeclaredFace(name))).toEqual(before)
})
it('clears previous browser registrations on a subsequent failed or missing font load',async()=>{
 vi.stubGlobal('document',{fonts:{load:vi.fn().mockResolvedValue([{}])}})
 await loadDocxBundledFonts()
 expect(browserFontFace('Noto Sans CJK SC')).not.toBeNull()
 vi.stubGlobal('document',{fonts:{load:vi.fn().mockRejectedValue(new Error('load failed'))}})
 await loadDocxBundledFonts()
 expect(browserFontFace('Noto Sans CJK SC')).toBeNull()
})
it('registers successful faces only and preserves actual document embedded face priority',async()=>{
 vi.stubGlobal('document',{fonts:{load:vi.fn().mockImplementation((font:string)=>Promise.resolve(font.includes('Sans')?[{}]:[]))}})
 await loadDocxBundledFonts()
 expect(browserFontFace('Noto Sans CJK SC')).not.toBeNull()
 expect(browserFontFace('Noto Serif CJK SC')).toBeNull()
 setResolverEmbeddedFaces([{family:'Noto Sans CJK SC',ascent:1,descent:0.2,lineGap:0,eastAsian:true}])
 expect(resolveDeclaredFace('Noto Sans CJK SC')).toMatchObject({source:'embedded',metrics:{ascent:1,descent:0.2}})
 expect(browserFontFace('Noto Sans CJK SC')).toBeNull()
})

it.each(['LXGW WenKai','Ma Shan Zheng','ZCOOL XiaoWei'])('registers %s as a Chinese face with its own metrics',async family=>{
 vi.stubGlobal('document',{fonts:{load:vi.fn().mockResolvedValue([{}])}})
 await loadDocxBundledFonts()
 expect(browserFontFace(family)).toMatchObject({eastAsian:true})
 expect(runFaceDecls({font:family,eastAsiaFont:family,fontAscii:'Calibri'},null).decls.find(value=>value.startsWith('--doc-east-asian-font:'))).toContain(family)
})

it('keeps Word layout substitutions separate from successfully loaded browser glyph faces',async()=>{
 const faces=['Noto Serif CJK SC','Noto Sans CJK SC','LXGW WenKai']
 const baseline=faces.map(f=>({word:resolveDeclaredFace(f),factor:lineHeightFactor(f),latin:latinLineFactor(f),cjk:cjkDeclaredLineFactor(f)}))
 vi.stubGlobal('document',{fonts:{load:vi.fn().mockResolvedValue([{}])}})
 await loadDocxBundledFonts()
 expect(faces.map(f=>({word:resolveDeclaredFace(f),factor:lineHeightFactor(f),latin:latinLineFactor(f),cjk:cjkDeclaredLineFactor(f)}))).toEqual(baseline)
 expect(browserFontFace('Noto Serif CJK SC')).toMatchObject({ascent:1.151,descent:.286,hheaTotal:1.437})
 expect(runFaceDecls({font:'Noto Serif CJK SC',eastAsiaFont:'Noto Serif CJK SC',fontAscii:'Calibri'},null).decls.find(d=>d.startsWith('--doc-east-asian-font:'))).toContain("'KR Theme Latin GO','Noto Serif CJK SC'")
})

it('preserves Word Latin substitution before the selected browser East Asian face',async()=>{
 vi.stubGlobal('document',{fonts:{load:vi.fn().mockResolvedValue([{}])}})
 await loadDocxBundledFonts()
 const both=runFaceDecls({font:'Noto Serif CJK SC',eastAsiaFont:'Noto Serif CJK SC',fontAscii:'Noto Serif CJK SC'},null)
 expect(both.family).toMatch(/^'KR Theme Latin GO','Noto Serif CJK SC'/)
 const separate=runFaceDecls({font:'Noto Serif CJK SC',eastAsiaFont:'Noto Serif CJK SC',fontAscii:'Arial'},null)
 expect(separate.family).toMatch(/^'Arial'/)
 expect(separate.family).toContain("'Noto Serif CJK SC'")
 expect(separate.family!.indexOf("'Arial'")).toBeLessThan(separate.family!.indexOf("'Noto Serif CJK SC'"))
 const eaOnly=runFaceDecls({font:'Noto Serif CJK SC',eastAsiaFont:'Noto Serif CJK SC'},null)
 expect(eaOnly.family).toMatch(/^var\(--doc-latin-chain,/)
 expect(eaOnly.family).toContain("'Noto Serif CJK SC'")
})
