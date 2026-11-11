export interface SlideComment { authorId: number; idx: number; author: string; initials: string; dt: string; text: string }
export interface SlideComments { items: SlideComment[]; readOnlyReason: string | null }
export type CommentEdit = { slideIndex: number; kind: 'add'; clientId: string; text: string } | { slideIndex: number; kind: 'delete'; authorId: number; idx: number }
const identity = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0

export function commentTextError(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return '请输入批注内容'
  if (value.length > 10000) return '批注内容不能超过 10000 个字符'
  for (const char of value) {
    const point = char.codePointAt(0)!
    if (!(point === 9 || point === 10 || point === 13 || point >= 0x20 && point <= 0xd7ff || point >= 0xe000 && point <= 0xfffd || point >= 0x10000 && point <= 0x10ffff)) return '批注内容含无法保存的字符'
  }
  return null
}

export function sourceComments(value: unknown): SlideComments {
  const source = value as SlideComments | undefined
  if (!source || !Array.isArray(source.items) || !(source.readOnlyReason === null || typeof source.readOnlyReason === 'string')) return { items: [], readOnlyReason: '尚未读取可核验的经典批注来源，请重新打开文件' }
  if (source.items.some(item => !item || !identity(item.authorId) || !identity(item.idx) || ['author', 'initials', 'dt', 'text'].some(key => typeof item[key as keyof SlideComment] !== 'string'))) return { items: [], readOnlyReason: '批注来源身份或内容无效，暂不能修改' }
  const duplicate = new Set(source.items.map(item => item.authorId + ':' + item.idx)).size !== source.items.length
  return { items: source.items, readOnlyReason: source.readOnlyReason !== null ? source.readOnlyReason || '批注来源暂不能安全修改' : duplicate ? '批注来源身份不唯一，暂不能修改' : null }
}

/** 先验证整批再交给宿主写入；仅允许引用原始来源页和原始批注身份。 */
export function validateCommentEdits(value: unknown, slides: { comments?: SlideComments }[], deletedSlides: number[] = []): CommentEdit[] {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > 500) throw new Error('批注操作无效或超过 500 条')
  const added = new Set<string>(), removed = new Set<string>()
  for (const edit of value) {
    if (!edit || typeof edit !== 'object' || !identity(edit.slideIndex) || edit.slideIndex >= slides.length) throw new Error('批注来源页身份无效')
    if (deletedSlides.includes(edit.slideIndex)) throw new Error('批注操作不能与删除同一来源页同时保存')
    const source = sourceComments(slides[edit.slideIndex]!.comments)
    if (source.readOnlyReason) throw new Error('批注来源只读：' + source.readOnlyReason)
    if (edit.kind === 'add') {
      if (Object.keys(edit).sort().join() !== 'clientId,kind,slideIndex,text' || typeof edit.clientId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(edit.clientId) || added.has(edit.clientId)) throw new Error('新增批注身份无效或重复')
      const reason = commentTextError(edit.text)
      if (reason) throw new Error(reason)
      added.add(edit.clientId)
    } else if (edit.kind === 'delete') {
      const key = edit.slideIndex + ':' + edit.authorId + ':' + edit.idx
      if (Object.keys(edit).sort().join() !== 'authorId,idx,kind,slideIndex' || !identity(edit.authorId) || !identity(edit.idx) || removed.has(key) || source.items.filter(item => item.authorId === edit.authorId && item.idx === edit.idx).length !== 1) throw new Error('删除批注的来源身份无效或重复')
      removed.add(key)
    } else throw new Error('批注操作类型无效')
  }
  return value.map(edit => ({ ...edit }))
}
