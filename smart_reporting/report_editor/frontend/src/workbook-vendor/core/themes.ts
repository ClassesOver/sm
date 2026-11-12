/**
 * Adapted from GenOffice `apps/sheets/src/renderer/themes.ts` at
 * f8c17004fb730df11f0f743164ffd8b4281bb38c (upstream SHA-256
 * 42f527e0319a2d35c33d574256c683dfe74a9138db4aa2be54cdd735afc04f23).
 *
 * Page Layout > Themes / Colors / Fonts preset data, copied verbatim: the
 * scheme interfaces, the `scheme` helper, COLOR_SCHEMES, FONT_SCHEMES,
 * FONT_BY_THEME and THEME_PRESETS. Palettes are in theme index order
 * [lt1, dk1, lt2, dk2, accent1-6, hlink, folHlink], the order the engine's
 * setThemePart writer expects.
 *
 * Local adaptation: the upstream renderer-side recolouring (`applyTint`,
 * `rethemeStyles`, typed against the desktop `WorkbookCellStyle`) is not
 * copied; the native editor re-renders by replaying the operation through the
 * real workbook engine, so theme-provenance styles resolve exactly as a reopen.
 */
export interface ThemeColorScheme {
  readonly id: string
  readonly name: string
  /// #RRGGBB in theme index order, 12 entries.
  readonly values: readonly string[]
}

export interface ThemeFontScheme {
  readonly id: string
  readonly name: string
  readonly major: string
  readonly minor: string
}

export interface ThemePreset {
  readonly id: string
  readonly name: string
  readonly colors: ThemeColorScheme
  readonly fonts: ThemeFontScheme
}

/// dk1/lt1/dk2/lt2/accents/hlink (clrScheme semantics) → theme index order.
const scheme = (
  id: string,
  name: string,
  dk1: string,
  lt1: string,
  dk2: string,
  lt2: string,
  accents: readonly [string, string, string, string, string, string],
  hlink: string,
): ThemeColorScheme => ({
  id,
  name,
  values: [lt1, dk1, lt2, dk2, ...accents, hlink, '954F72'].map((value) => `#${value}`),
})

export const COLOR_SCHEMES: readonly ThemeColorScheme[] = [
  scheme(
    'office',
    'Office',
    '000000',
    'FFFFFF',
    '44546A',
    'E7E6E6',
    ['4472C4', 'ED7D31', 'A5A5A5', 'FFC000', '5B9BD5', '70AD47'],
    '0563C1',
  ),
  scheme(
    'ember',
    'Ember',
    '2B1B14',
    'FFFFFF',
    '632B1A',
    'F7EBE6',
    ['C43E1C', 'E97132', 'FFC000', '8A3B12', 'D98F73', 'A33517'],
    'C43E1C',
  ),
  scheme(
    'indigo',
    'Indigo',
    '1F2A44',
    'FFFFFF',
    '3B4C77',
    'E8ECF6',
    ['2E4FA3', '5B79C7', '8FA6DE', 'E97132', '31A5A0', '7030A0'],
    '2E4FA3',
  ),
  scheme(
    'forest',
    'Forest',
    '1E2B20',
    'FFFFFF',
    '375E43',
    'E9F2EB',
    ['217346', '4EA72E', '92D050', 'FFC000', '3E8E8B', '70AD47'],
    '217346',
  ),
  scheme(
    'cream',
    'Cream',
    '3B3226',
    'FBF6EC',
    '6E5F49',
    'F0E7D5',
    ['C0A062', '8A6D3B', 'B65C33', '6E8B5E', '4E7CA1', '9E5D74'],
    '8A6D3B',
  ),
  scheme(
    'rose',
    'Rose',
    '3A1F33',
    'FFFFFF',
    '6E3A62',
    'F8ECF4',
    ['B44582', 'D96FA8', 'E9A6C9', '7030A0', 'E97132', '4E7CA1'],
    'B44582',
  ),
  scheme(
    'graphite',
    'Graphite',
    'F2F2F2',
    '1E1E1E',
    'D9D9D9',
    '333333',
    ['4FC3F7', 'FFB74D', '81C784', 'BA68C8', 'E57373', '90A4AE'],
    '4FC3F7',
  ),
  scheme(
    'midnight',
    'Midnight',
    'EAF2FF',
    '0F1C2E',
    'BCD0EC',
    '1E3350',
    ['4A9EDE', '63C7B2', 'F2C14E', 'E4718D', '9B8CDE', '7FB069'],
    '6FB3EC',
  ),
]

export const FONT_SCHEMES: readonly ThemeFontScheme[] = [
  { id: 'office', name: 'Office', major: 'Calibri Light', minor: 'Calibri' },
  { id: 'arial', name: 'Arial', major: 'Arial', minor: 'Arial' },
  { id: 'georgia', name: 'Georgia', major: 'Georgia', minor: 'Georgia' },
  { id: 'candara', name: 'Candara', major: 'Candara', minor: 'Candara' },
  { id: 'segoe', name: 'Segoe UI', major: 'Segoe UI', minor: 'Segoe UI' },
  { id: 'trebuchet', name: 'Trebuchet MS', major: 'Trebuchet MS', minor: 'Calibri' },
]

const FONT_BY_THEME: Record<string, string> = {
  office: 'office',
  ember: 'trebuchet',
  indigo: 'segoe',
  forest: 'candara',
  cream: 'georgia',
  rose: 'trebuchet',
  graphite: 'segoe',
  midnight: 'office',
}

export const THEME_PRESETS: readonly ThemePreset[] = COLOR_SCHEMES.map((colors) => ({
  id: colors.id,
  name: colors.name,
  colors,
  fonts: FONT_SCHEMES.find((fonts) => fonts.id === FONT_BY_THEME[colors.id]) ?? FONT_SCHEMES[0]!,
}))
