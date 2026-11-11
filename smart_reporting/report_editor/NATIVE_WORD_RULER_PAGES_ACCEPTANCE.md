# Word 标尺与导航页面限定范围验收

日期：2026-11-11。固定 GenOffice HEAD：f8c17004fb730df11f0f743164ffd8b4281bb38c。

后续增量：左／首行／悬挂标尺缩进已按可信单段范围接通并完成真实拖动、保存下载及重开验收，见 [标尺缩进增量验收](NATIVE_WORD_RULER_INDENT_ACCEPTANCE.md)。下文保留本专项当时的范围和历史证据。

## 交付范围

- 标尺原封迁入 Ruler.tsx、use-measurement.ts、units.ts，SOURCE/LOCAL 身份清单已登记。宿主支持显示/隐藏、缩放对齐、当前节左右边距和可信原有顶层单段右缩进；沿用现有 Guard、原生操作、草稿及撤销链。只读仍可显示。
- 制表位、左缩进、首行及悬挂缩进明确禁用并说明原因。现有协议的左缩进仅支持720 twips整倍数，不能将源任意拖动值直接保存。列表、表格、跨段、新增未保存段落、镜像边距及多栏右缩进均未开放。
- 拖动复核文档、选区、节设置、显示比例及写锁；隐藏/销毁清理源 document 监听和辅助线。提交被拒绝后重建源标记，防止保留拖动预览的错误位置。
- 导航新增“页面”标签，页数仅取既有同源分页的真实 cuts，正文范围取实测 blocks。页面组件为 continuous PM 本地适配：固定源 NavPageThumbs 依赖 live page-wrap/gap ledger，不能直接在当前无间隔画布使用，不声称完整迁入该组件。
- 仅支持同尺寸、同左右边距、单栏且可精确整块分页的正文缩略图；复杂段内/表格拆页、分栏、镜像、竖排、浮动或纵向对齐等显示具体不支持原因。缩略图不包含页眉页脚，不等同打印预览。
- 克隆纸张 inert，清除重复身份、编辑属性与可执行资源；点击定位真实来源块，不修改正文/草稿。请求、文档、缩放、可见性、标签和销毁使旧结果失效。页面标签先恢复页面视图；其后切回大纲会立即失效页面并回到标题标签。
- 导航与首末页页眉页脚入口共用 measurePagination，避免复制分页规则；测量暂时中和 PM 自身显示缩放并在成功/失败后恢复。

## 最终证据

证据根：/tmp/sr-word-ruler-pages-20261111。

冻结产物 final2-static；manifest SHA256：
3aca7a4c54574145b7225aff9d72ac14f4ad3d2bc7ba9dfb23653b5bafd97c7a。

冻结引擎 final-engine/dist/edit-docx.mjs SHA256：
688ef055b324a7a6fa77581b995cf4933a343599afaea7caed790885c9a681dc。

232个源码快照构建前后无漂移；integration-verification.json 汇总最终复核。原封新增vendor文件和清单身份通过。

- controls-green.log：标尺15、分页测量7、页面17、标题导航8、导航搜索15，共62项通过。
- outline-red.log → outline-green.log：大纲切换失效回归先失败后通过，新增1项。
- integration-final.log：视图/只读Ribbon/首末页HF身份及复用布局8项通过。
- 未运行完整测试。上述71项为本轮分别执行的定向检查。
- tsc-verified.log：npx tsc --noEmit 退出0。
- final2-build.log：Vite 构建退出0。最终全部JS预算通过，未修改预算阈值；预算契约检查退出0。Word main255130、render723388、engine423900、ruler17611、navigation17607 bytes。
- 标尺最终浏览器 final2-ruler-browser/result.json：只读/可编辑两场景通过，130个实际加载JS与冻结磁盘SHA一致，errors=[]；100%及110%尺规与纸张左右位置/宽度一致。源键盘操作、UndoRedo、右缩进90、左边距1530、真实保存下载和修订2重开通过。
- 页面最终浏览器 final2-pages-browser/evidence.json：只读/可编辑真实三页，各页正文准确分离；150%仍为三页；点击定位、标题往返、关闭重开、大纲往返及 inert 焦点保护通过。正文JSON/localStorage不变，0保存/导出，130个JS身份一致，errors=[]。
- 独立 ZIP/lxml 回读 independent-xml-verification.json：右缩进90及 rightChars=0、左边距1530、右边距1440。文件成员仅 document.xml 和 core.xml 变化；其余文件原bytes保留。既有桥接另规范化目标 w:t 的 xml:space、更新core修订/时间，并增加ZIP目录项；扣除这些明确变化后正文XML完全相同。
- root目视标尺重开和页面截图：尺规居中对齐、标签和三页缩略图均可见。

浏览器使用真实 Python DOCX、真实编辑器和真实Node桥，但授权/修订登记为fixture HTTP；验收失败仍可下载为fixture UI验证，不冒充生产鉴权或真实发布签发整链。本轮未改发布链，未提交、推送或部署。完整Word对齐仍未完成。
