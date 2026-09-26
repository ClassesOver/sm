const HEADING_LABELS: Record<string, number> = {
  一级标题: 1,
  二级标题: 2,
  三级标题: 3,
  四级标题: 4,
  五级标题: 5,
  六级标题: 6,
}

// Crepe 斜杠菜单的标题项没有任何可区分的 class/属性，六项渲染得一模一样。
// 菜单每次打开都会重建 li，用 MutationObserver 在出现时按文本打上
// data-heading-level，CSS 据此预览各级标题的字号/字重差异。
export function installSlashMenuHeadingPreview(target: HTMLElement | Document = document) {
  const tagItems = (scope: ParentNode) => {
    scope.querySelectorAll('.milkdown-slash-menu li').forEach((li) => {
      const label = li.textContent?.trim() ?? ''
      const level = HEADING_LABELS[label]
      if (level) li.setAttribute('data-heading-level', String(level))
      else li.removeAttribute('data-heading-level')
    })
  }
  tagItems(target)
  const observer = new MutationObserver(() => tagItems(target))
  observer.observe(target === document ? document.body : (target as HTMLElement), {
    childList: true,
    subtree: true,
  })
  return () => observer.disconnect()
}
