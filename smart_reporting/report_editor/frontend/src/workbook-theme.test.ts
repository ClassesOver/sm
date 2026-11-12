import { afterEach, describe, expect, it, vi } from 'vitest'
import { mountWorkbookRibbon } from './workbook-ribbon'
import { THEME_MENU_OPTIONS, readWorkbookThemeSource, themeOperation, themeSourceFromXml } from './workbook-theme'
import { COLOR_SCHEMES, FONT_SCHEMES, THEME_PRESETS } from './workbook-vendor/core/themes'

const slots = ['dk1', 'lt1', 'dk2', 'lt2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink']
const themeXml = (fonts = true) => '<a:theme><a:themeElements><a:clrScheme name="Office">' + slots.map(slot => `<a:${slot}><a:srgbClr val="000000"/></a:${slot}>`).join('') + '</a:clrScheme>'
  + (fonts ? '<a:fontScheme name="Office &amp; Co"><a:majorFont><a:latin typeface="Calibri Light"/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/></a:minorFont></a:fontScheme>' : '') + '</a:themeElements></a:theme>'

afterEach(() => { document.body.replaceChildren() })

describe('workbook theme (pinned page-layout-actions theme / theme-colors / theme-fonts)', () => {
  it('reads availability and current names from the theme part', () => {
    expect(themeSourceFromXml(themeXml())).toEqual({ available: true, fontsAvailable: true, colorName: 'Office', fontName: 'Office & Co' })
    expect(themeSourceFromXml(themeXml(false))).toMatchObject({ available: true, fontsAvailable: false })
    expect(themeSourceFromXml(undefined)).toMatchObject({ available: false, reason: '工作簿没有主题部件，无法应用主题' })
    expect(themeSourceFromXml(themeXml().replace(/<a:hlink>.*?<\/a:hlink>/, ''))).toMatchObject({ available: false, reason: '主题缺少完整的配色方案，无法应用主题' })
  })

  it('never blocks loading when the theme part cannot be read', async () => {
    expect(await readWorkbookThemeSource(new Uint8Array([1, 2, 3]))).toEqual({ available: false, fontsAvailable: false, reason: '无法读取工作簿主题部件，主题暂不可用' })
  })

  it('builds the pinned preset payloads for theme, colors and fonts', () => {
    const source = themeSourceFromXml(themeXml())
    const ember = COLOR_SCHEMES.find(item => item.id === 'ember')!
    expect(themeOperation('theme', 'ember', source)).toEqual({ name: 'Ember', operation: { kind: 'setThemePart', themePath: 'xl/theme/theme1.xml', state: {
      colors: { name: 'Ember', values: [...ember.values] }, fonts: { name: 'Trebuchet MS', major: 'Trebuchet MS', minor: 'Calibri' } } } })
    expect(themeOperation('theme-colors', 'forest', source).operation.state).toEqual({ colors: { name: 'Forest', values: [...COLOR_SCHEMES.find(item => item.id === 'forest')!.values] } })
    expect(themeOperation('theme-fonts', 'georgia', source).operation.state).toEqual({ fonts: { name: 'Georgia', major: 'Georgia', minor: 'Georgia' } })
    // 没有字体方案：主题只换配色，字体不可用
    const noFonts = themeSourceFromXml(themeXml(false))
    expect(themeOperation('theme', 'ember', noFonts).operation.state).toEqual({ colors: { name: 'Ember', values: [...ember.values] } })
    expect(() => themeOperation('theme-fonts', 'arial', noFonts)).toThrow('主题没有可改写的字体方案')
    expect(() => themeOperation('theme', 'ember', themeSourceFromXml(undefined))).toThrow('没有主题部件')
    expect(() => themeOperation('theme-colors', 'missing', source)).toThrow('未知的主题预设')
    expect(THEME_PRESETS.every(preset => preset.colors.values.length === 12 && preset.colors.values.every(value => /^#[0-9A-F]{6}$/.test(value)))).toBe(true)
    expect(FONT_SCHEMES.map(item => item.id)).toEqual(['office', 'arial', 'georgia', 'candara', 'segoe', 'trebuchet'])
  })

  it('renders the three menus, dispatches the picked preset and reflects availability', () => {
    const command = vi.fn(); let state: { colorName?: string; fontName?: string; reason?: string; fontsReason?: string } | undefined = { colorName: 'Office', fontName: 'Office' }, editable = true
    const ribbon = mountWorkbookRibbon(document.body, command, { editable: () => editable, rotation: () => 0, theme: () => state })
    document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Page Layout"]')!.click()
    const menu = (id: string) => document.querySelector<HTMLSelectElement>(`[data-ribbon-menu="${id}"]`)!
    expect([...menu('theme').options].slice(1).map(option => option.textContent)).toEqual(THEME_MENU_OPTIONS.theme.map(item => item.label))
    expect(menu('theme-colors').title).toBe('颜色（当前：Office）')
    menu('theme').value = 'midnight'; menu('theme').dispatchEvent(new Event('change'))
    expect(command).toHaveBeenLastCalledWith('theme:midnight'); expect(menu('theme').value).toBe('')
    menu('theme-fonts').value = 'segoe'; menu('theme-fonts').dispatchEvent(new Event('change'))
    expect(command).toHaveBeenLastCalledWith('theme-fonts:segoe')
    expect(document.querySelector('[data-ribbon-command="theme"]')).toBeNull()
    const effects = document.querySelector<HTMLButtonElement>('[data-ribbon-command="theme-effects"]')!
    expect(effects.disabled).toBe(true); expect(effects.title).toBe('固定源未提供主题效果写入')
    state = { colorName: 'Office', fontsReason: '主题没有可改写的字体方案' }; ribbon.refreshState()
    expect(menu('theme-fonts').disabled).toBe(true); expect(menu('theme-colors').disabled).toBe(false)
    state = { reason: '工作簿没有主题部件，无法应用主题' }; ribbon.refreshState()
    expect(['theme', 'theme-colors', 'theme-fonts'].every(id => menu(id).disabled && menu(id).title === '工作簿没有主题部件，无法应用主题')).toBe(true)
    state = { colorName: 'Office', fontName: 'Office' }; editable = false; ribbon.refreshState()
    expect(menu('theme').disabled).toBe(true)
    ribbon.dispose()
  })
})
