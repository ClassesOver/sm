import { pageBordersXml } from '../packages/docx-engine/src/section'
import type { SectionSettings } from '../packages/docx-engine/src/types'

type SectionPatch = Omit<Partial<SectionSettings>, 'pageBorderProps'> & { pageBorderProps?: SectionSettings['pageBorderProps'] | null }

/** 源“方框”快捷项移除自定义属性；未改边框的其余节设置照常保留来源。 */
export function docxSectionSettingsWithPatch(settings: SectionSettings, patch: SectionPatch = {}): SectionSettings {
  const { pageBorderProps, ...rest } = patch
  const result: SectionSettings = { ...settings, ...rest }
  if (pageBorderProps != null) result.pageBorderProps = pageBorderProps
  if (patch.pageBorderProps === null || patch.pageBorder === false || patch.pageBorder === true && !Object.hasOwn(patch, 'pageBorderProps')) delete result.pageBorderProps
  return result
}
export function docxDefaultPageBox(settings: SectionSettings) {
  return settings.pageBorder && pageBordersXml(settings.pageBorderProps) === pageBordersXml(undefined)
}
