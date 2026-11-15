# XLSX 活动行列突出显示：固定来源与本地缺口

2026-11-10。仅只读核对源码、既有调查与测试，执行一次现有定向用例及两个无文件写入的源码探针，新增本文；不修改生产或测试，不构建、不运行完整套件、不提交。列宽批次文件保持冻结。

## 确认的差异

固定 GenOffice 支持 View「突出显示活动行和列」：开启后，随主活动单元格移动，在当前可见 canvas 上绘制对应行、列的背景带。它是阅读视图偏好，不改单元格格式、不写 XLSX、不创建编辑草稿。当前本地仍显示同名按钮，但按钮被明确禁用，原因是「尚未实现活动行列突出显示视图」；没有找到对应 canvas 扩展或控制器。

复现本地行为：打开任意 XLSX，点击 View，定位 `[data-ribbon-command="toggle-cross-highlight"]`。按钮为 disabled，title/aria-description 给出上述原因；不能像固定来源一样打开后移动活动格观察高亮。该差异与刚完成的透视来源删除、重命名、行列编辑保护无关。

`NATIVE_WORD_XLSX_PARITY_AUDIT.md:93` 已把 cross-highlight 列在未完成 View 能力中，但同一旧清单还列了后来已交付的编辑栏、标题和 RTL，因此本文重新核对实际实现，不把旧表所有项目继续算作缺口。未在现有 acceptance 记录中找到本项交付证据。

## 固定来源证据

固定仓库 `/home/junge/pros/genoffice-source-full`，实际 HEAD 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。以下路径相对该仓库；不可变根为 https://github.com/ahaodev/genoffice/tree/f8c17004fb730df11f0f743164ffd8b4281bb38c 。

| 位置 | 实际行为 |
| --- | --- |
| `apps/sheets/src/renderer/ExcelShell.tsx:3334` | View check-item 调用 `onCommand('toggle-cross-highlight')`，勾选态来自 `crossHighlightVisible`。 |
| `apps/sheets/src/renderer/App.tsx:691,2550,3933,4726` | 初始化读取偏好、安装控制器、同步可见状态；按钮只切换 state、保存偏好和反馈消息，随后返回。 |
| `apps/sheets/src/renderer/cross-highlight.tsx:52` | `crossHighlightRects` 只针对 viewport 可见范围生成行、列矩形，支持冻结窗格的多个分段并去重；不依赖已用数据区域，也没有 20k 行上限。 |
| 同文件 `:110–129` | `ai-sheets-cross-highlight` localStorage 偏好，默认关闭；存储不可用时保留会话状态。 |
| 同文件 `:154` | 从 `getActiveCell()` 取主活动格，不把所选矩形左上角当活动格。 |
| 同文件 `:190–243` | `SheetExtension` 的 Z_INDEX=22，在单元格背景之上、字体与边框之下绘制；`ctx.__mode==='printing'` 跳过；校验 workbook/sheet identity，使用主题颜色。 |
| 同文件 `:264–324` | 监听 SelectionChanged / ActiveSheetChanged，只更新当前状态并 makeDirty；dispose 注销监听并清除显示，不创建每次选区变化的浮动 DOM。 |
| `apps/sheets/tests/cross-highlight.test.ts` | 已有来源用例覆盖普通/冻结分段/远处空白格、主活动格、偏好和生命周期；本轮只读，未运行来源套件。 |

来源 helper SHA-256：`74390d8cfbda80486de266b1cca554139f61220de2bd58062b8aa8d1bf0cbe38`。

## 本地证据与本轮实际执行

路径相对 `smart_reporting/report_editor/frontend`：

- `src/workbook-ribbon.ts:516` 声明同名 View 按钮；`:577` 的 `disabledReasons` 保存精确原因；`:1219–1221` 渲染时设置 disabled/title/aria-description；`:595–596` 直接调用通用 helper 时也会抛出该不可用原因。
- `src/workbook-main.ts` 没有本项专用 handler、state、扩展安装或 dispose；全仓搜索本地 `cross-highlight/crossHighlight`，除按钮、不可用原因和旧 View 测试外，没有对应实现。现有 formula-bar 会话视图控制器是相邻可参考模式，不是本项已经完成的证据。
- `src/workbook-ribbon.test.ts:626–655` 的旧 View 测试包含本项禁用预期。定向运行一次：`./node_modules/.bin/vitest run src/workbook-ribbon.test.ts -t 'renders GenOffice View controls with a live gridline toggle and explicit unavailable states'`，日志 `/tmp/xlsx-cross-highlight-local-gap.log`，**exit 1**。它先在已交付的 `toggle-formula-bar` 旧禁用断言失败，未执行到 cross-highlight 断言；不能把此失败解释成 cross-highlight 动态验收结果，也不能称该文件通过。本轮未改旧测试。
- 为避免借旧测试推断本项状态，另以 TypeScript AST 读取当前 `workbook-ribbon.ts`：确认 action 声明存在、disabled reason 精确匹配，并逐行核对实际渲染分支。探针 exit 0，输出 `/tmp/xlsx-cross-highlight-local-proof.log`。这是当前代码事实检查，不是浏览器像素验收。
- 对固定源原文件的 `crossHighlightRects` 函数体做内存 TypeScript transpile 后执行，未改算法。活动格 `(row=4,column=2)`、viewport 行0..9/列0..5、每格10×20，实际返回 `row(left=0,top=80,width=60,height=20)` 和 `column(left=20,top=0,width=10,height=200)`，exit 0。它证明来源纯几何语义，不声称运行过来源应用或本地浏览器。

AST 核对可在上述 frontend 目录复现，无测试或文件修改：

```bash
node --input-type=module <<'JS'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from './node_modules/typescript/lib/typescript.js'
const file='src/workbook-ribbon.ts'
const source=ts.createSourceFile(file,readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true)
let reason,declared=false
function visit(node){
  if(ts.isVariableDeclaration(node)&&node.name.getText(source)==='disabledReasons'&&node.initializer&&ts.isObjectLiteralExpression(node.initializer)){
    const p=node.initializer.properties.find(p=>p.name&&ts.isStringLiteral(p.name)&&p.name.text==='toggle-cross-highlight')
    reason=p?.initializer?.text
  }
  if(ts.isCallExpression(node)&&node.expression.getText(source)==='action'&&node.arguments.some(a=>ts.isStringLiteral(a)&&a.text==='toggle-cross-highlight'))declared=true
  ts.forEachChild(node,visit)
}
visit(source)
assert(declared)
assert.equal(reason,'尚未实现活动行列突出显示视图')
console.log({declared,reason})
JS
```

## 下一次最小实施范围

迁入上述固定来源独立 canvas helper，并记录来源 SHA；使用现有 Univer `SheetExtension`/render service/event API，不新造浮动 DOM 高亮或写单元格 fill。接入 main 安装、初始偏好、切换、工作簿替换/主题刷新及 dispose；Ribbon 移除本项不可用原因，设置真实 pressed 状态。优先复用现有会话视图控制模式，独立于编辑权限处理，不把阅读视图记成 dirty。

明确限定本轮为活动行列阅读高亮：不同时接打印分页预览、窗口拆分、图表创建或其他尚未完成命令。无需扩展 XLSX 模型、保存 operation、Python whitelist 或 OOXML writer；用户偏好也不应进入来源哈希绑定的 NativeDraft。若偏好 key 与固定源应用共用会冲突，可用宿主现有偏好命名约定，但应在验收中明确。

固定来源 helper 使用模块级 renderState/全局 registry：迁入前需确认宿主同页面多编辑器与重复 mount/dispose 的隔离，不应直接复制后假定安全。冻结窗格、RTL、缩放及隐藏行列均由真实 skeleton/viewport 坐标验证，不能只拿纯矩形用例代替浏览器布局结果。

## 最小验收清单

1. 固定来源几何向量：普通格、主活动格与选区左上不同、冻结分段、远处空白格、非法坐标；只按可见范围计算。
2. main/Ribbon：开关 pressed 状态、移动活动格与跨页跟随、只读/保护来源可阅读、保存中采用宿主明确的视图可用策略；切换不改变完整 snapshot、单元格样式、undo/redo、NativeDraft、保存标签或 revision。
3. 生命周期函数：默认关闭、偏好刷新恢复、存储拒绝时会话可切换、主题刷新、重复 mount/dispose、多实例不串目标；长时间导航不累积订阅/浮动组件。
4. 生产 Chromium：真实 View 点击，普通表/空白远处格/冻结/缩放/RTL 截图验证高亮与文字边框层级；图表/控件仍可交互，关闭后无残影；实际静态 JS 200/SHA 与无 pageErrors。
5. 文件与打印负面边界：切换前后实际 XLSX 下载 SHA 不变（或保存已有无关真实编辑时 ZIP 中不存在任何高亮专属字段），打印输出不带阅读高亮。无需把本项误包装成新下载/发布链路。

当前结论仅为**已确认但尚未实施的独立 View 差异**，不代表全量 XLSX 对齐完成，也不影响已验收透视来源或本轮冻结的 Word 列宽状态。

## 2026-11-10 实施状态（构建浏览器验收前）

上述独立 View 差异已完成最小实施，先前“尚未实施”是调研时状态。
来源与宿主 SHA、宿主适配记录见 `frontend/src/workbook-vendor/SOURCE.md`
的 cross-highlight host module 段；文件位于宿主 `src`，未混入 vendor 目录哈希。
真实 Worksheet WeakMap 隔离替代上游模块单例状态，并适配当前 Univer 的
官方 selection command 监听。只读来源可用，切换仅写阅读偏好。

定向验收已通过：helper/Ribbon 11 passed，main 1 passed，新增只读恢复及
存储异常 2 passed；最终 `tsc --noEmit` exit 0。未重复完整测试。
`smoke/workbook-cross-highlight-built-smoke.mjs` 已准备并通过语法检查，
等待 root 统一 build 后执行；当前不宣称生产画布像素已验收。
该探针采用源文件色块上的实际混色像素与关闭恢复比率，覆盖普通、冻结、
150% 缩放、RTL、反向扩选主活动格及 25001 行空白格，并核对草稿、
undo/redo、保存态、来源文件 SHA 与刷新恢复偏好。

首轮 built 像素验收确认普通、冻结、150% 缩放的色块内部混色及关闭恢复
均 100%；同时发现上游 RTL 反序坐标令行宽为负，实际缺少行高亮。
已增加 RTL RED 向量并将行边界改为端点 min/max，5 个几何向量 GREEN；
新增隐藏活动行/列零尺寸向量 GREEN，列上下边界保持原样。
来源文档宿主 SHA 随修复更新。等待下一轮统一 build 后重验相同像素断言。

独立待查导航差异：真实 built 浏览器在跨表 `Far!Z25001` 定位后，名称框
已显示 Z25001、Far 标签已激活，但画布仍显示 A1 起始视口；因此屏外
活动行列没有可绘制交集。原始证据：
`/tmp/xlsx-cross-highlight-built-far-navigation-failure.log` 和
`/tmp/cross-highlight-built-spnz1C/failure.png`。本轮不修改 goto 生产逻辑；
高亮验收通过真实 ArrowDown/ArrowUp 导航将该远处目标滚入视口后再测。
该导航行为应独立调查，不能据此宣称 goto 全部对齐。

## 2026-11-10 最终 built 验收

root 统一构建（含 RTL 修复）后，独立探针
`frontend/smoke/workbook-cross-highlight-built-smoke.mjs` exit 0；最终日志：
`/tmp/xlsx-cross-highlight-built-smoke.log`。截图和实际文件目录：
`/tmp/cross-highlight-built-AAfR14`。

普通、冻结、150% 缩放、RTL、反向 C5:D6 扩选主格 D6 的色块内部混色
与关闭恢复比率均为 100%。反向扩选另由原生剪贴板确认实际 C5:D6 矩阵；
远处 Z25001 空白格经真实键盘滚入后，检测到 85182 个高亮像素，实际
列/行带分别覆盖 664/1363 像素，关闭恢复 100%。230 个静态 JS 响应
200 且内容 SHA 匹配构建文件；无 pageErrors；刷新恢复阅读偏好。
草稿存储、undo/redo 可用性、保存态全程精确不变，save 请求 0。
真实 XLSX 下载入口点击前后所得文件与来源 SHA 相同：
`e665e4fae5b03534db912e65f188055a84553d1eb8aefe390144cc4397c11e2f`。
打印禁画由定向 extension 单元用例覆盖，本轮未执行独立浏览器打印。
前述 goto 只选不滚动差异仍独立待查，本轮未修改。
