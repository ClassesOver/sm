import { createHash } from 'node:crypto'
import { readFile, mkdir, writeFile, stat } from 'node:fs/promises'
import { dirname, extname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { JSDOM } from 'jsdom'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const sourceRoot = join(frontend, 'src')

// 只枚举代码声明，不将出现一个按钮或存在一个回调等同于功能验收通过。
export function inspectUiSource(text, file = 'component.tsx') {
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true,
    file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const imports = new Set(), sites = [], templates = []
  const value = node => node && (ts.isStringLiteralLike(node) ? node.text : node.getText(source).slice(0, 180))
  const add = (node, kind, details) => sites.push({ line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1, kind, ...details })
  const inspectTemplate = (node, origin) => {
    const expressions = []
    const fragment = expression => {
      if (ts.isStringLiteralLike(expression)) return expression.text
      if (ts.isParenthesizedExpression(expression)) return fragment(expression.expression)
      if (ts.isTemplateExpression(expression)) return expression.head.text + expression.templateSpans.map(span => fragment(span.expression) + span.literal.text).join('')
      if (ts.isBinaryExpression(expression) && expression.operatorToken.kind === ts.SyntaxKind.PlusToken) return fragment(expression.left) + fragment(expression.right)
      const index = expressions.push(expression.getText(source)) - 1
      return `__OFFICE_UI_EXPRESSION_${index}__`
    }
    // 默认不执行脚本、不加载外部资源；动态插值仅保留原表达式用于后续核查。
    const dom = new JSDOM(fragment(node), { includeNodeLocations: true })
    const controls = dom.window.document.querySelectorAll('button,input,select,textarea,option,fieldset,a[href],[role],[tabindex],[aria-label],[aria-labelledby],[data-command],[data-action]')
    const marker = /__OFFICE_UI_EXPRESSION_\d+__/g
    const readable = text => (text ?? '').replace(marker, '[动态表达式]').replace(/\s+/g, ' ').trim()
    for (const control of controls) {
      const attributes = Object.fromEntries([...control.attributes]
        .filter(attribute => /^(?:aria-.+|data-.+|id|name|class|type|role|title|tabindex|disabled|hidden|readonly|required|checked|selected|href|value|multiple)$/.test(attribute.name))
        .map(attribute => [attribute.name, attribute.value === '' ? true : attribute.value]))
      const labelledBy = (control.getAttribute('aria-labelledby') ?? '').split(/\s+/).map(id => dom.window.document.getElementById(id)?.textContent ?? '').join(' ').trim()
      const labels = [...(control.labels ?? [])].map(label => {
        const copy = label.cloneNode(true)
        copy.querySelectorAll('button,input,select,textarea').forEach(child => child.remove())
        return copy.textContent
      }).join(' ')
      const legend = control.localName === 'fieldset' ? [...control.children].find(child => child.localName === 'legend')?.textContent : ''
      add(node, 'html-control', { origin, tag: control.localName, htmlLine: dom.nodeLocation(control)?.startLine,
        label: readable(control.getAttribute('aria-label') ?? (labelledBy || legend || labels || control.getAttribute('title') || control.textContent)),
        attributes, dynamic: /__OFFICE_UI_EXPRESSION_\d+__/.test(control.outerHTML) })
    }
    templates.push({ line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1, origin, controls: controls.length, expressions })
    dom.window.close()
  }
  const visit = node => {
    if ((ts.isImportDeclaration(node) && !node.importClause?.isTypeOnly || ts.isExportDeclaration(node) && !node.isTypeOnly)
      && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) imports.add(node.moduleSpecifier.text)
    if (ts.isCallExpression(node)) {
      const callee = node.expression.getText(source)
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) imports.add(node.arguments[0].text)
      if (/(?:^|\.)(?:createElement|createElementNS)$/.test(callee)) add(node, 'element', { tag: value(node.arguments[callee.endsWith('NS') ? 1 : 0]) })
      if (/^(?:createModal|useModalDialog)$/.test(callee)) add(node, 'modal', { factory: callee })
      if (callee === 'createModal' && node.arguments[0]) {
        const argument = node.arguments[0]
        const content = ts.isObjectLiteralExpression(argument) && argument.properties.find(property => ts.isPropertyAssignment(property) && property.name && (property.name.text === 'content'))
        if (content) inspectTemplate(content.initializer, 'modal-content')
        else inspectTemplate(argument, 'modal-content')
      }
    }
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const attributes = Object.fromEntries(node.attributes.properties.filter(ts.isJsxAttribute)
        .filter(attribute => /^(?:aria-label|title|className|role|data-command|data-action|disabled)$/.test(attribute.name.getText(source)))
        .map(attribute => [attribute.name.getText(source), value(attribute.initializer) ?? true]))
      add(node, 'jsx', { tag: node.tagName.getText(source), attributes })
    }
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
      && ts.isPropertyAccessExpression(node.left) && node.left.name.text === 'innerHTML') {
      add(node, 'html-template', { content: value(node.right) })
      inspectTemplate(node.right, 'innerHTML')
    }
    if (ts.isObjectLiteralExpression(node)) {
      const properties = Object.fromEntries(node.properties.filter(ts.isPropertyAssignment).map(property => [property.name.getText(source), property.initializer]))
      if (properties.id && properties.label) {
        add(node, 'control-definition', Object.fromEntries(['id', 'label', 'kind', 'command', 'disabled', 'sourceActionId']
          .filter(key => properties[key]).map(key => [key, value(properties[key])])))
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return { imports: [...imports].sort(), sites, templates }
}

function formatOf(file) {
  if (/(?:^|\/)(?:docx[-.]|vendor\/genoffice-docs\/)/.test(file)) return 'docx'
  if (/(?:^|\/)(?:workbook[-.]|workbook-vendor\/)/.test(file)) return 'xlsx'
  if (/(?:^|\/)(?:slides[-.]|vendor\/genoffice-slides\/|vendor\/genoffice\/)/.test(file)) return 'pptx'
  if (/(?:^|\/)pdf[-.]/.test(file)) return 'pdf'
  return 'shared'
}

async function localImport(from, specifier) {
  const aliases = {
    '@genoffice/ui': './vendor/genoffice-docs/packages/ui/src/browser.ts',
    '@genoffice/i18n': './vendor/genoffice-docs/packages/i18n/src/index.ts',
    '@genoffice/font-metrics/resolve': './vendor/genoffice-docs/packages/font-metrics/src/resolve.ts',
  }
  if (aliases[specifier]) return resolve(sourceRoot, aliases[specifier])
  if (!specifier.startsWith('.')) return null
  const path = resolve(dirname(from), specifier)
  if (!path.startsWith(sourceRoot + '/')) return null
  for (const candidate of [path, ...['.ts', '.tsx', '.css', '/index.ts', '/index.tsx'].map(suffix => path + suffix)]) {
    try { if ((await stat(candidate)).isFile()) return candidate } catch (error) { if (error.code !== 'ENOENT' && error.code !== 'ENOTDIR') throw error }
  }
  throw new Error(`未解析本地导入 ${relative(frontend, from)}: ${specifier}`)
}

export async function buildOfficeUiInventory() {
  const entries = ['src/unified-main.ts', 'src/native-main.ts', 'src/slides-main.ts']
  const pending = entries.map(file => join(frontend, file)), visited = new Set(), modules = []
  while (pending.length) {
    const path = pending.pop()
    if (visited.has(path)) continue
    visited.add(path)
    if (!['.ts', '.tsx', '.css'].includes(extname(path))) continue
    const text = await readFile(path, 'utf8'), file = relative(frontend, path)
    const parsed = path.endsWith('.css') ? { imports: [], sites: [], templates: [] } : inspectUiSource(text, file)
    modules.push({ file, format: formatOf(file.slice(4)), sha256: createHash('sha256').update(text).digest('hex'),
      stylesheet: path.endsWith('.css'), sites: parsed.sites, templates: parsed.templates })
    for (const specifier of parsed.imports) {
      const dependency = await localImport(path, specifier)
      if (dependency) pending.push(dependency)
    }
  }
  modules.sort((a, b) => a.file.localeCompare(b.file))
  return { schema: 2, entries, boundary: '原生入口可达的 src 相对导入闭包及 Vite 本地 UI/i18n/font-metrics 别名；含本地 vendor。展开innerHTML与createModal content的静态HTML控件；动态插值不执行、不假定穷尽，单独登记。控件line是模板表达式的源码行，htmlLine是解析片段行。仍不含外部npm/引擎包、运行时计算出的入口和桌面原生菜单。声明点不是功能或运行验收分母。', modules }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const outputFlag = process.argv.indexOf('--output-dir')
  if (outputFlag < 0 || !process.argv[outputFlag + 1]) throw new Error('使用 --output-dir 指定清单输出目录')
  const directory = resolve(process.argv[outputFlag + 1]), inventory = await buildOfficeUiInventory()
  await mkdir(directory, { recursive: true })
  await writeFile(join(directory, 'inventory.json'), JSON.stringify(inventory, null, 2) + '\n')
  const rows = ['# 四格式 UI 源码声明清单', '', inventory.boundary, '', '| 格式 | 可达模块 | UI 声明点 | 样式表 |', '| --- | ---: | ---: | ---: |']
  for (const format of ['xlsx', 'pdf', 'docx', 'pptx', 'shared']) {
    const modules = inventory.modules.filter(module => module.format === format)
    rows.push(`| ${format} | ${modules.length} | ${modules.reduce((count, module) => count + module.sites.length, 0)} | ${modules.filter(module => module.stylesheet).length} |`)
  }
  rows.push('', '## UI 模块定位', '', '| 格式 | 文件 | 声明点 |', '| --- | --- | ---: |')
  for (const module of inventory.modules.filter(module => module.sites.length)) rows.push(`| ${module.format} | ${module.file} | ${module.sites.length} |`)
  await writeFile(join(directory, 'inventory.md'), rows.join('\n') + '\n')
  const cell = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\|/g, '\\|').replace(/\r?\n/g, ' ')
  const templateRows = ['# 四格式 HTML 模板控件定位', '', inventory.boundary, '',
    '本表只定位源码声明，不根据标签、按钮存在或回调存在推断功能通过。声明名称是静态标签/文本摘要，不是完整的运行时可访问名称计算。所有条目仍待映射具体构建的运行证据；历史已验收组件不会因此变为失败。模板行用于跳到表达式，片段行不是源码行；重复声明不是独立功能。', '',
    '| 格式 | 文件 | 模板行 | 片段行 | 元素 | 声明名称 | 定位/状态属性 | 含动态内容 | 运行证据 |',
    '| --- | --- | ---: | ---: | --- | --- | --- | --- | --- |']
  for (const module of inventory.modules) for (const site of module.sites.filter(site => site.kind === 'html-control')) {
    const attributes = Object.fromEntries(Object.entries(site.attributes).filter(([name]) => /^(?:data-.+|id|name|type|role|disabled|hidden|readonly|checked|selected)$/.test(name)))
    templateRows.push('| ' + [module.format, module.file, site.line, site.htmlLine, site.tag, site.label, JSON.stringify(attributes), site.dynamic ? '是' : '否', '待映射'].map(cell).join(' | ') + ' |')
  }
  templateRows.push('', '## 动态模板待核查', '', '这里只列摘要，不求值。完整表达式与来源见同次生成的inventory.json；变量、条件分支、循环生成及外部组件需另做运行核查。', '',
    '| 格式 | 文件 | 模板行 | 来源 | 已声明静态控件 | 动态表达式摘要 |', '| --- | --- | ---: | --- | ---: | --- |')
  for (const module of inventory.modules) for (const template of module.templates.filter(template => template.expressions.length)) {
    templateRows.push('| ' + [module.format, module.file, template.line, template.origin, template.controls, template.expressions.join('; ').slice(0, 240)].map(cell).join(' | ') + ' |')
  }
  await writeFile(join(directory, 'template-controls.md'), templateRows.join('\n') + '\n')
  console.log(JSON.stringify({ directory, modules: inventory.modules.length, sites: inventory.modules.reduce((count, module) => count + module.sites.length, 0) }))
}
