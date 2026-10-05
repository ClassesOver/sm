// B8 在线定位：导出文件中的链接指向编辑页并携带 ?subject=<subjectId>，
// 页面加载完成后读取该参数并自动打开对应来源对象。subjectId 长度上限与
// 后端冻结契约（SubjectBindingV1）一致；空值或超限不猜测、不打开。
const MAX_SUBJECT_ID_LENGTH = 128

export function linkedSubjectFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get('subject')
  if (value === null || value === '') return null
  return value.length <= MAX_SUBJECT_ID_LENGTH ? value : null
}
