import { LexerTreeBuilder } from '@univerjs/engine-formula'

// 只迁移显式本地表引用的表名；外部工作簿限定符属于同一词法节点，不会匹配。
export function renameTableReferences(formula: string, oldName: string, newName: string): string {
  const nodes = new LexerTreeBuilder().sequenceNodesBuilder(formula.replace(/[\r\n]/g, ' '))
  if (!nodes) return formula
  let rewritten = formula
  const offset = formula.startsWith('=') ? 1 : 0
  for (const node of [...nodes].reverse()) {
    if (typeof node === 'string' || node.nodeType !== 3) continue
    const bracket = node.token.indexOf('[')
    if (bracket <= 0 || node.token.slice(0, bracket).toLowerCase() !== oldName.toLowerCase()) continue
    const start = node.startIndex + offset
    rewritten = rewritten.slice(0, start) + newName + rewritten.slice(start + bracket)
  }
  return rewritten
}

// 使用官方词法节点定位表引用，字符串常量与其他表保持原样。
export function renameTableColumns(formula: string, tableName: string, renames: ReadonlyMap<string, string>): string {
  return renameStructuredColumns(formula, tableName, renames)
}

// 调用方必须先由公式所在工作表与坐标确定所属表；此处不猜测隐式引用作用域。
export function renameImplicitTableColumns(formula: string, renames: ReadonlyMap<string, string>): string {
  return renameStructuredColumns(formula, undefined, renames)
}

function implicitColumnToken(token: string): boolean {
  let depth = 0
  for (let index = 0; index < token.length; index++) {
    const char = token[index]
    if (depth === 0 && char !== '[') return false
    if (char === "'") { index++; continue }
    if (char === '[') depth++
    else if (char === ']') { depth--; if (depth < 0) return false }
  }
  // lexer可将最后一个右括号保留为独立节点；禁止括号之外的工作簿/工作表限定符。
  return depth === 0 || depth === 1
}

function renameStructuredColumns(formula: string, tableName: string | undefined, renames: ReadonlyMap<string, string>): string {
  // 保持 UTF-16 长度，避免官方 lexer 将末尾 CRLF 合成单个空格后偏移原文坐标。
  const nodes = new LexerTreeBuilder().sequenceNodesBuilder(formula.replace(/[\r\n]/g, ' '))
  if (!nodes) return formula
  let rewritten = formula
  const offset = formula.startsWith('=') ? 1 : 0
  for (const node of [...nodes].reverse()) {
    if (typeof node === 'string' || node.nodeType !== 3) continue
    const bracket = node.token.indexOf('[')
    if (tableName === undefined
      ? bracket !== 0 || !implicitColumnToken(node.token)
      : bracket < 0 || node.token.slice(0, bracket).toLowerCase() !== tableName.toLowerCase()) continue
    const start = node.startIndex + offset, end = node.endIndex + offset + 1
    const original = formula.slice(start, end)
    // 官方 lexer 将最后一个右方括号保留为独立节点；补齐后只修改叶子列名。
    const replacementToken = (original + ']').replace(/\[((?:'[\s\S]|[^\[\]])*)\]/g, (full, text: string) => {
      if (text.startsWith('#')) return full
      const prefix = text.startsWith('@') ? '@' : ''
      const name = text.slice(prefix.length).replace(/'([\s\S])/g, '$1')
      const replacement = renames.get(name.toLowerCase())
      return replacement === undefined ? full : '[' + prefix + replacement.replace(/['\[\]#@]/g, char => "'" + char) + ']'
    }).slice(0, -1)
    rewritten = rewritten.slice(0, start) + replacementToken + rewritten.slice(end)
  }
  return rewritten
}
