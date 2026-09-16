export function imageDescriptionStatus(editor: HTMLElement) {
  const missing = Array.from(editor.querySelectorAll<HTMLImageElement>('img')).filter(
    (image) => !image.alt.trim(),
  ).length
  return missing
    ? { label: `图片缺少说明 ${missing} 张`, warning: true }
    : { label: '图片说明完整', warning: false }
}
