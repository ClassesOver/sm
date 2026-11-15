# Word 导航搜索、网格线及渲染分包增量

日期：2026-11-11。固定 GenOffice HEAD：f8c17004fb730df11f0f743164ffd8b4281bb38c。

本轮沿用现有导航和视图模型：导航内纯字面查找复用源 find 核心；网格线仅切换源 show-grid class 和已有24px屏幕辅助样式。Word docGrid、表格网格线、页缩略图、标题编辑、标尺均不属于本轮交付。

## 定向测试与构建

- 网格线真实 Editor/NativeDraft 4项 RED→GREEN；源默认关闭，readonly可切，不dispatch PM事务，不写正文/草稿/storage。
- 主视图路由新增网格线回归 RED→GREEN，相关6项视图测试通过；只读Ribbon网格线动作/按下状态及原导航大纲代表用例2项通过。
- 导航搜索限定当前 PM 正文/表格，不含页眉页脚、docProtected或独立嵌套编辑器，不跨段；无替换和正文全局高亮。结果列表遵守源cap，上下个可遍历全部匹配。搜索结果定位前返回页面视图，避免大纲隐藏正文。
- 导航搜索首轮新增12项与旧7项合计19项GREEN；后续仅新增3项验证页面恢复callback、外部updateState回滚/public refresh、硬换行与纯字面边界，先RED再GREEN。
- 已定位PDF文本导出通过protocol/opSignatures带入AI操作registry闭包。仅调分包：5个独占模块归serializer，修订渲染共享的table-ops单列，两个宿主导航模块独立；不改源运行逻辑或预算阈值。
- Vite独立冻结构建exit0，16个相关源文件构建前后无漂移，原文件备份在frozen-source。manifest=8e5131fa4fb5fe7f784f3e4803f2a60307df5b876d2bd87b8d1a7e610a94ba92。
- Word render从783110降至723373 bytes（阈值727040）；main251159（阈值256000）、navigation9697、engine423900、table-ops17248、serializer67656，相关预算全部通过。
- 完整tsc仍exit2，仅Slides/XLSX错误；全局预算仍有pdf-main259.3KiB、workbook-engine443.3KiB、workbook-main270.2KiB超限，不据此宣称全局通过。
- 导航搜索、网格线与真实built文本导出适配函数浏览器验收均已通过；具体层次与边界如下。

证据目录：/tmp/sr-word-view-tools-20261111；不重复完整测试，不涉及发布签发链路，不提交/推送/部署。

## 最终冻结浏览器证据

- 导航搜索：navigation-search-browser/evidence.json；Chromium140.0.7339.16，可编辑与只读两场景，各128个实际JS的响应/磁盘SHA一致，errors=[]，6个context/file/preview请求，0保存/导出。跨run非BMP精确选区、表格、^p/^/.*纯字面与HTML文本安全、500条列表/503处全部循环跳转、已有查找两处高亮保留、大纲搜索结果返回页面均通过。动态正文编辑后结果更新，导航不追加既有草稿/Undo；root目视editable.png。
- 网格线：gridlines-browser/final/result.json；均匀双栏、只读、两节混排三场景，各128个实际JS身份通过，errors=[]，0保存/导出。computed style为源两方向渐变、24px×24px、content-box；正文/页面列坐标CSS/全部storage/NativeDraft/保存状态不变，已有编辑可真实UndoRedo；大纲往返仍维持原网格开关。root目视mixed-grid.png。
- 分包后真实消费者：budget-runtime-browser/evidence.json与chunk-analysis.json；空probe页只动态import冻结built PDF文本导出适配模块，真实Python DOCX包含Heading1、正文、粗体、3×2表格，分别实际调用renderPdfTextExport得到Markdown/HTML。标题、正文、粗体、表格内容通过；HTML无script，Editor清理无残留，人工核对告警保留。96个实际JS身份一致，errors=[]，98请求无/api/；输出output.md/output.html与runtime.png可回读，root已核验。
- 三项manifest开始/结束均与上述冻结身份一致。root另行逐个复核128/128/96个实际JS磁盘SHA并汇总于integration-verification.json；引擎桥SHA仍ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6。
- 网格线首轮mixed快照仅style属性null与空字符串不同，实际CSS一致；只改smoke比较style.cssText后GREEN，失败html/png保留，生产没有因此变更。

## 依赖与预算复核

source级protocol→ops→style/field/table操作注册闭包为新增体积来源；仅把运行时独占的5个AI模块并入serializer，共享table-ops独立为叶包。新导航包仅两个宿主模块，源find/headings/nav-outline仍共享render，PM仍native-tiptap。

最终Word静态闭包不包含serializer；文本适配消费者按需加载它。新导航/table-ops/serializer没有循环，构建既有locale循环告警与上轮各36条，无新增。预算仍用原checkBuildBudget，未放宽阈值；render减少59737 bytes，相关Word包全部在阈值内。

## 限制与后续

- 搜索不含页眉页脚、受保护对象、独立嵌套编辑器，不跨段落；无替换、正文全局高亮、页面缩略图、标题移动/删除/升降级。saving/异步失效/dispose/失败refresh由定向unit覆盖，未冒充全部浏览器覆盖。
- 网格线是源屏幕辅助开关，不是Word docGrid或表格网格线编辑；复用的源CSS未限定media screen，本轮没有验证浏览器打印隐藏网格。
- 浏览器Word路由为fixture；真实Python创建/inspect与真实编辑器并不等于生产鉴权整链。分包验证为真实built adapter+真实DOCX输入，没有真实PDF授权转换、服务端发布、下载签发或模型调用。
- 全局tsc与PDF/XLSX预算限制见上文；不宣称全局检查通过。验收后共享vite.config.ts仅被并行任务追加PDF form-controls分包规则，本轮Word规则仍在；其它15个快照文件未漂移。浏览器结论严格对应本次冻结产物，不替后续并行构建背书。
- 本轮没有提交、推送或部署。完整Word对齐仍未完成。
