import { describe,it,expect } from 'vitest'
import { withDocxTheme, docxThemeOperations } from './docx-theme'
describe('document themes',()=>{it('merges independent font/color choices and retains one source-bound operation',()=>{
const model={fonts:{major:'Old',minor:'Old'},colors:{},editable:true,readOnlyReason:null,expectedThemeSha256:'a'.repeat(64)}
const first=withDocxTheme([],model,{fontPreset:'ribbonThemeFontYahei'})
const next=withDocxTheme(first,model,{colorPreset:'ribbonColorBlue'})
expect(next).toHaveLength(1);expect(next[0]).toMatchObject({fontPreset:'ribbonThemeFontYahei',colorPreset:'ribbonColorBlue'})
expect(docxThemeOperations(next,model)).toEqual(next)
expect(()=>docxThemeOperations(next,{...model,expectedThemeSha256:'b'.repeat(64)})).toThrow()
expect(()=>withDocxTheme(next,{...model,editable:false},{fontPreset:'ribbonThemeFontArial'})).toThrow()
})})
it('preserves theme base while independently overriding one component',()=>{
const model={fonts:{major:'Old',minor:'Old'},colors:{},editable:true,readOnlyReason:null,expectedThemeSha256:'a'.repeat(64)}
const first=withDocxTheme([],model,{themePreset:'ribbonThemeFacet'})
const next=withDocxTheme(first,model,{fontPreset:'ribbonThemeFontKaiti'})
expect(next[0]).toMatchObject({themePreset:'ribbonThemeFacet',fontPreset:'ribbonThemeFontKaiti'})
expect(withDocxTheme(next,model,{themePreset:'ribbonThemeIon'})[0]).not.toHaveProperty('fontPreset')
})
import { effectiveDocxTheme } from './docx-theme'
it('projects the theme and independent overrides for live CSS',()=>{
const model={fonts:{major:'Old',minor:'Old'},colors:{},editable:true,readOnlyReason:null,expectedThemeSha256:'a'.repeat(64)}
const ops=withDocxTheme(withDocxTheme([],model,{themePreset:'ribbonThemeFacet'}),model,{fontPreset:'ribbonThemeFontKaiti'})
expect(effectiveDocxTheme(ops,model)).toMatchObject({fonts:{major:'楷体'},colors:{name:'Facet',accent1:'90C226'}})
expect(effectiveDocxTheme([],model).fonts?.minor).toBe('Old')
})
