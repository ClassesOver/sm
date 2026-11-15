# XLSX AI 来源图表新增与系列换绑验收

日期：2026-11-13。固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批关闭来源图表协议、候选及保存子链的明确范围；四格式完整 AI 工具、复杂图表视觉和可恢复长任务仍开放。

## 实现范围

- Agno `propose_operations` 接受源 DSL `add_chart` 与 `edit_chart(seriesData)`，翻译为原生 `applyChartSource.operation`；Python 许可表与 XLSX delivery 操作白名单均登记该操作。
- 新增支持 column／bar／line／area／pie／doughnut／scatter／radar／combo 九类，来源范围最多 2000 格；仅接受真实工作表、范围、标题和锚点等描述，不接受模型填写的缓存值。
- 共享 `chartAdditionFromGrid` 位于原生 XLSX 引擎，手工入口保留 re-export。桥在操作重放时读取真实工作簿，人工未保存值参与新增和换绑；引用与缓存同步生成。
- 换绑定位唯一可信 chartPath 与存在的系列索引，支持来源表、单行／列 valuesRange／categoriesRange、名称与既有格式字段；检查范围长度、重复索引及目标存在性。只在整簿授权开放，选区授权不放行图表；不与行列／工作表结构操作混批。
- 复用候选预览、显式拒绝／采纳、UndoRedo、草稿恢复与原生保存下载；不自动采纳或保存。校验失败保持原件及人工草稿。

## RED→GREEN 与真实引擎

1. 初始未注册操作、工具翻译／非工具 planner 校验及第二 delivery 白名单分别产生失败，修复后专项通过；历史日志保留。
2. 本次重现 `/tmp/native-ai-chart-sources-resume-red-20261113.log`：2 failed／23 passed。环形图错误沿用饼图单系列截断；纯数值数据序号分类被写成数值列引用。按固定源分类引用条件修复共享构造器，仅饼图保留第一系列。
3. `/tmp/native-ai-chart-sources-resume-green-20261113.log`：25 passed。覆盖九图类、草稿实际值、转义表名、明确锚点、来源／向量／索引拒绝、原图与未触及 part 保全。
4. 手工入口 `/tmp/native-ai-chart-grid-resume-20261113.log`：5 passed；引擎 `npm run typecheck` 与 `npm run bundle:bridges` 退出 0，日志分别为 `/tmp/native-ai-chart-source-resume-typecheck-20261113.log` 和 `/tmp/native-ai-chart-source-resume-bundle-20261113.log`。
5. Python 专项 `/tmp/native-ai-chart-sources-resume-python-20261113.log`：15 passed，仅既有 imghdr 弃用告警。含真实 Agno ScriptedModel、真实引擎、候选采纳与 openpyxl／lxml 独立回读；人工 B3=73 与人工文字保留，原件不变。此批不重复整个项目测试。
6. 最终协议说明修改后另跑 `test_workbook_ai_tools.py`：22 passed，仅同一既有 imghdr 告警，日志 `/tmp/native-ai-chart-sources-toolkit-final-20261113.log`。目标 ruff、smoke JS 语法及局部 diff 空白检查通过。

## 冻结构建与浏览器保存链

final8 构建 `/tmp/native-ai-chart-sources-final8-build-20261113.log` 退出 0（Vite 45.17 秒）；`check:budget` 退出 0，日志 `/tmp/native-ai-chart-sources-final8-budget-20261113.log`。预算未提高，Word 119.3 KiB、PDF 239.7 KiB、workbook-main 222.9 KiB、workbook-engine 344.9 KiB。既有 chunk／依赖注释告警保留。

冻结资产 `/tmp/native-ai-chart-sources-final8-20261113/static`，manifest SHA256 `80fe3f19bd9146dfcefab08789e3e59b670ffa0b2cb73b1a4b50ff89bd27e73b`。

浏览器 `/tmp/native-ai-chart-sources-browser-20261113-final8/summary.json` 为 `ok=true`：真实 Chromium／FastAPI／grant／CSRF／工作区／Agno ScriptedModel／原生 writer。172 份实际 JS／CSS 响应与冻结磁盘逐资源匹配，pageErrors／consoleErrors／httpErrors／assetErrors 均为空。

已验证拒绝首个候选、重新生成与采纳、UndoRedo、刷新恢复、两次保存与实际下载、新修订 4→5→6 重开。独立 ZIP／openpyxl／lxml 检查图表数 2→3→3、来源 A1:B3／锚点 E20、换绑 A3／B3 后仅 `xl/charts/chart3.xml` 内容变化，两张原图保持字节一致；人工 A1 加粗保留。

| 文件 | SHA256 |
| --- | --- |
| 来源 | `c351d761e05df5d95990242e6f86dafcceb977fa9fd5d027499b5a7c3daab4e1` |
| 新增修订 5 | `8509d77feafc8164b32e7764898d0ac31052763d09c51b12d205af59d1c64b77` |
| 换绑修订 6 | `b5c4e623045a5e056fa787b7663c2747e50171ee62aa95255b4947b4a038ac7c` |

两次保存继续返回 `validation.ok=false`／`native_source_review_pending`，实际文件照常签发下载，未将业务／完整版式验收标为通过。修订仓储为内存夹具，非生产数据库验收。

## 真实 provider：单独一层证据

`frontend/smoke/workbook-ai-chart-sources-provider.py` 复用实际环境模型配置、Agno、原生授权／工作区与 writer，使用合成工作簿、内存修订仓储；没有浏览器与保存下载。模型 `deepseek-v4.1-flash`。

失败历史保留：

- `/tmp/native-ai-chart-sources-provider-20261113/summary.json`：工具调用混淆源 op 与原生 kind／arguments 包装，校验拒绝后任务失败。补完整调用示例，未放宽校验。
- `/tmp/native-ai-chart-sources-provider-20261113-fixed/summary.json`：两任务生成候选并采纳，最终跨两次重放比较 ZIP 总 SHA 失败。离线重放诊断 `/tmp/native-ai-chart-replay-timestamp-diagnosis-20261113.json` 证明 part 内容相同，仅 JSZip 写入时间不同；未为探针改写生产 ZIP 时间策略。
- `/tmp/native-ai-chart-sources-provider-20261113-preview-bytes/summary.json`：修正预览字节采集后，新增通过；换绑首候选漏了要求的标题，后续补交被已冻结候选规则拒绝。独立标题断言准确揭示失败，不删除断言或更改原任务来隐藏。

补清“一次提交全部要求，成功后直接结束”的工具协议，换绑示例包含 title。最终 `/tmp/native-ai-chart-sources-provider-20261113-complete-proposal/summary.json` 为 `ok=true`：新增 8.45 秒、换绑 8.48 秒，均显式采纳。探针只观察真实 writer 输出，不替代其结果；实际预览字节 SHA 必须等于返回的 draftSha256，再与独立重放逐 part 比较；openpyxl／lxml 检查人工 B3=73、标题、分类／数值引用与缓存 10/73→73，两张原图和来源文件保持不变。

## 保留边界与后续

- root 已目视 final8 新增和换绑截图：新增折线可见、锚点区域无重叠；单点换绑后的折线仅标题可见、没有可见点标记。该画布缺口未关闭，不能称图表视觉完整对齐。非普通图表轴／标记／复杂标签与完整格式仍需源语义核验。
- 当前来源桥不代表所有源 DSL／复杂结构组合、shape／image／sparkline 或新文档 AI 完成。
- 真实 provider 探针与 ScriptedModel 浏览器是不同运行；生产数据库＋真实 provider＋浏览器显式采纳＋新修订保存下载重开仍未完成同链验收。
- 任务、事件仍主要在内存；后续复用 task_execution 仓储／租约／取消／预算与既有原生身份上下文，不能以文件修订持久化替代任务重启恢复。
- 临时 chunk 诊断配置已归档至 `/tmp/vite.native-ai-diagnostic-20261113.config.ts` 并从工作树删除。未提交、推送、部署；整体目标继续进行。
