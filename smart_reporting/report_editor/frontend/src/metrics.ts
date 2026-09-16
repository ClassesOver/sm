export function documentMetrics(markdown: string): string {
  const characters = markdown.replace(/\s/g, '').length
  const paragraphs = markdown.split(/\n\s*\n/).filter((part) => part.trim()).length
  const minutes = Math.max(1, Math.ceil(characters / 350))
  return `${characters} 字 · ${paragraphs} 段 · 阅读 ${minutes} 分钟`
}
