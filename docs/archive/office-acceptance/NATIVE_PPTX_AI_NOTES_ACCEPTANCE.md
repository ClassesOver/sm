# PPTX AI 演讲者备注增量验收

本增量对齐固定 GenOffice `slides-skill.ts` 的 `apply_ops / setNotes`；保留 Agno 原生工具循环、现有 SSE 进度、真实引擎预览和显式采纳。它不表示四格式完整工具面已对齐。

## 合同与授权

- 当前对象、当前页画布、整稿画布授权均不隐含演讲者备注。新增“当前页演讲者备注”“整稿演讲者备注”选项，wire 为 `scope: notes` 与显式 `selection: [{slideIndex}]`，最多100页。
- 原生候选协议独立增加 `notesEdits: [{slideIndex,text}]`，不扩张旧报告 `SlidesAIProposal`。备注按实际来源的 `notesEditable` 能力、页身份、唯一性、每页20000及总200000 UTF16字符校验；文字规范化沿用现有引擎合同。
- 工具先读取授权页备注和该页只读正文资料，分页覆盖完整后才能提出修改。未授权页备注不进入工具回执；画布对象保持不可写。
- 当前备注草稿从真实引擎 inspect 回填，重排后按原始页身份映射；合并时按 slideIndex 替换目标备注，保留其他人工操作和未选页。输入法或无效备注未提交时不能生成候选。
- 采纳前展示备注前后差异，不提前写入草稿；采纳继续核验原件 SHA、完整草稿快照与任务身份。

## 当前证据

- API 严格授权形状专项1项通过；前端按页授权、差异展示、等待显式采纳专项1项通过。
- 后端 schema/工具、草稿页序映射、真实引擎与实际 Agno 工具链证据见 `/tmp/slides-ai-notes-*.log`；真实引擎文件位于 `/tmp/slides-ai-notes-real-engine-fixed/`。人工生成测试来源必须注册 notes master；缺失注册的来源被原引擎正确拒绝，未放宽安全能力。
- 最终构建、实际浏览器与真实 provider 验收进行中；结果完成后追加，不能把 ScriptedModel 视为真实模型证明。

## 最终备注与透视分包证据

- 冻结构建 `/tmp/office-ai-notes-final-20261111/static`：Vite42.81秒通过，manifest `fc9e359e9d2b7bd6133df49f9dacd012022f6869100d0675daa70d0083c28aeb`，全部包体预算通过。通用workbook-engine393.2KiB，透视功能拆至既有pivot-calculation51.0KiB，未提高预算；9项分派及预算契约通过。
- 实际built浏览器 `/tmp/office-ai-notes-browser-20261111/summary.json` ok=true，117实际JS逐个网络/磁盘SHA核验，候选前草稿保持人工备注，差异可见，浮窗查看后采纳；真实路由/授权/Agno ScriptedModel/引擎，独立python-pptx核验目标备注、其他页秘密备注及画布表图均正确；无save/export POST，JS/console/HTTP错误为空。root独立重核manifest、117资源、候选SHA并目视截图。
- 新分包实际运行 `/tmp/office-ai-notes-pivot-built-20261111/evidence.json` ok=true，同manifest、143实际JS SHA，真实透视创建及Python保存/下载、独立openpyxl/ZIP回读：华东60、华西40、总计100；无pageerror。HTTP身份及保存路由为fixture，真实文件补丁为native引擎。截图停留来源表，不冒称目标透视显示已验收。
- 真实 `deepseek-v4.1-flash`：`/tmp/pptx-ai-notes-real-provider-20261111.json` 15项全部通过，10.58秒首轮完成，人工草稿42/17被真实读取，目标备注正确、未授权页备注未进入工具回执，原件SHA不变，ZIP仅目标notesSlide1.xml内容变化。原始false是验证器把JSZip新增目录项当文件部件；保留`.initial.*`，仅对同一候选离线修正文件部件口径，没有重跑模型。root重核来源/候选SHA。
- 后端最终新增8项分批、旧工具/表图26项、API1、前端1项通过；生产/探针ruff和定向diff检查通过。全前端types仍受共享工作区中docx ruler接口及workbook-main控制变量的独立进行中改动影响，日志 `/tmp/office-ai-notes-final-types.log`，不能声明当前全量types通过。

## 后续视觉修正与构建边界

实际备注截图揭示旧`.slides-ai {align-items:start}`在切换flex后仍生效，导致输入框缩窄。共享布局追加`align-items:stretch`；原冻结build的新增几何断言先失败，修正CSS覆盖后桌面输入框330/面板358px、窄屏250/278px通过，页面错误为空。证据 `/tmp/office-ai-panel-layout-css-verified-20261111/summary.json`、desktop/narrow截图，源CSS SHA `7c152d80196503af1300e13e11bffb7304b34babdc4958cf08dd2b98ff21c160`；共享面板3项针对回归通过。

此视觉复验是在上述冻结JS上注入精确当前CSS，不是新发布构建。尝试生成含视觉修正的全量构建被共享工作区新增 `pdf-main.ts` 对尚不存在 `./pdf-form-text-properties` 的导入阻挡，日志 `/tmp/office-ai-panel-layout-final-build.log`。未伪造缺失模块，未改PDF独立功能；备注/透视成功证据仍归属于其明确冻结manifest，最终全量构建收尾保持开放。
