# 已有表单字段复制验收（2026-11-14）

本批支持实际来源的安全单 Widget 文本、复选框、下拉字段复制/重复/同文档跨页粘贴；保留当前值、默认值、必填、选项、字体与 AP。复制辅助对象图为私有副本，后续填写副本不改变原字段值或原 AP 资源闭包。整体验收仍未完成，不代表生产部署。

## 实现与范围

沿用 `createFormField`，可选 `copyFrom` 包含原 fieldName/widgetId/widgetIdentity/expectedWidgetSha256；服务端重新读取实际来源，不从前端显示值重建。全批在原始字节上验证身份、模板、名称和页面区域，随后仅由服务器重绑中间 SHA。新字段与 Widget 使用新引用；辅助图深复制，Parent/Kids/P/Rect 单独绑定。复用现有 NativeDraft、撤销恢复、预览确认和修订发布/下载链，没有新增发布接口或门禁。

- 来源：未保护/未签名、默认 UserUnit、直角旋转的安全 AcroForm，沿用创建能力的整体来源检查。
- 类型：安全独立单控件 text/checkbox/choice。radio、date、signature、动作/扩展属性、结构引用进入辅助图、超出对象/字节预算的字段拒绝复制并说明原因。
- 新名称限同父层级；父层级必须能组成合法新名。来源叶子含空格、数字起始可生成合法新叶子，原 copyFrom 名称不变。冲突/终端前缀/长度限制沿用现有规则。
- 副本保持原尺寸，可平移/删除/再次复制；保存前不允许改必填、默认值、选项、字体或尺寸，属性卡明确提示保存后再编辑，避免丢失原始语义。
- 同文档跨页复制可用，已有控件本身迁页、跨页 radio、跨文档/系统剪贴板及任意复杂来源仍未支持。副本可能与原字段重叠，不保证自动避让。

## 定向验证

| 验证 | 结果与证据 |
| --- | --- |
| 初始引擎 RED | `/tmp/pdf-source-copy-engine-red.log`：真实复制因未知 copyFrom 被拒绝；另一零写拒绝测试当时已通过。 |
| 引擎关联专项 | `/tmp/pdf-source-copy-engine-final.log`：20 项通过，覆盖新复制及原批创建、创建安全和层级。 |
| 最终复制专项 | `/tmp/pdf-source-copy-engine-final2.log`：5 项通过；新增父层级先 RED，补测真实 Times-BoldItalic AP、V/DV 不同及后续填写的原 AP 完整闭包不变；与上行有重叠，不相加计数。 |
| 前端初始 RED | `/tmp/pdf-source-copy-front-red.log`：3 项复制入口/协议失败、38 项通过。 |
| 前端关联专项 | `/tmp/pdf-source-copy-front-final.log`：111 项通过（5 文件），保留原 React act 警告。 |
| 最终命名与画布专项 | `/tmp/pdf-source-copy-names-red.log` 先失败；`/tmp/pdf-source-copy-front-final2.log` 为 42 项通过，含 clipboard 9 和画布 33；不重复整个 111 项集。 |
| 真实服务 | `/tmp/pdf-source-copy-service-final.log`：1 项通过，实际 preview/preview_file、未确认拒绝、确认保存、修订登记、下载、pypdf 与原来源字节核验；业务 validation.ok=false 保留实际下载，原文本功能开关关闭仍可设计字段。 |
| 全局类型 | `/tmp/pdf-source-copy-types-final.log` 与既有 632 条诊断基线比较；全局类型检查不通过，不能称项目全绿。初次新增测试 tuple 类型诊断已修正，相关失败日志保留。 |
| 独立复核 | 现有同模型 reviewer 静态复核，无 Critical/Important；最后父层级与安全叶名增量亦复核，无重要问题；未把静态复核称作测试。 |

服务夹具首轮写已存在路径失败，已改为独立来源文件；第二轮真实保存下载已执行，但独立验证把父节点 `customer` 误计为终端字段，最终验证同时检查终端集合及父 Kids 数量后通过。没有改弱产品字段树或签发约束。

## 真实浏览器与独立 PDF

使用源码 Vite、真实固定 FormDesignLayer/PDF.js 和隔离 CLI；API 适配仅提供实际 CLI 预览，不含生产授权/发布。真实服务验证由上面的 Python 测试独立承担。

1. `/tmp/pdf-source-copy-browser`：首次发现复制属性卡窄屏右侧溢出，未算通过。
2. `/tmp/pdf-source-copy-browser-fixed`：修复后完成来源文字快捷键复制/重复、跨页菜单粘贴、复选框跨页、下拉重复、Undo/Redo、刷新恢复、实际 PDF 预览。末尾 pypdf 验证把合法的 `[export, display]` 下拉选项对当普通字符串而退出，保留失败日志，不称整轮退出成功。
3. `/tmp/pdf-source-copy-browser-final`：仅从上一轮真实原来源和四项实际操作续验，不伪造 SHA/重新绑定身份。验证恢复草稿、390px 卡片、实际预览及 pypdf；`evidence.json` 为 ok:true，页面错误和 HTTP 错误为空。最终七字段，页面 Widget 数为 `[5,2]`，文字 Alice/DV Default name、复选框开启、下拉 B/DV A/两组选项对均保留，实际 AP 存在，来源不变。此最小续验没有重跑完整复制菜单/Undo 链。

窄屏卡片 left=62/right=382，clientWidth=scrollWidth=318；实际目视窄屏和实际预览截图。文档正文沿用宿主横向阅读布局，副本重叠属于允许范围。浏览器夹具保存时自动重绘为 Helvetica，非默认字体保真由上述引擎 Times-BoldItalic 独立场景证明，不冒称浏览器验证了非默认字体。

最后新增父层级能力限制后，隔离 CLI 再构建并对同一真实浏览器来源/四操作最小重算，`final-runtime-equivalence.json` 证明最终字节与实际浏览器预览完全相同，四项执行、零跳过；不重复完整浏览器或服务链。最终 CLI SHA256 为 `e33fea1918ec6a281df3f4f42039ccf1f452ee1c8cb77090ddf5cbb3f4fd2162`；该正常来源等价证据不替代新拒绝分支的定向单测。

Vite 仍输出 sibling 项目 fast-xml-parser/saxes/utif2 预扫描依赖告警，Python 有 imghdr 弃用提示；均保留在日志中。未修改共享 static/dist，未提交、推送或部署。
