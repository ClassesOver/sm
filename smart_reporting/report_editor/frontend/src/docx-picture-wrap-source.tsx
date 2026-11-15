import { pictureWrapOptions, type createDocxPictureFormatControls } from './docx-picture-format-controls'
import { Dropdown } from './vendor/genoffice-docs/packages/ui/src/dropdown'
import { zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'
import './vendor/genoffice-docs/packages/ui/src/dropdown.css'

const options = pictureWrapOptions.map(([value, label]) => ({ value: value ?? '', label }))

export function DocxPictureWrapSource({ controls }: { controls: ReturnType<typeof createDocxPictureFormatControls> }) {
  const wrap = controls.wrap()
  const disabled = controls.reason() !== null
  return (
    <Dropdown
      key={`${wrap?.key ?? ''}:${disabled}`}
      className="rb-wrap-dd"
      disabled={disabled}
      tip={zh.ribbonWrapText}
      ariaLabel={zh.ribbonWrapText}
      value={wrap?.value ?? ''}
      options={options}
      onPick={value => wrap?.pick(value)}
    />
  )
}
