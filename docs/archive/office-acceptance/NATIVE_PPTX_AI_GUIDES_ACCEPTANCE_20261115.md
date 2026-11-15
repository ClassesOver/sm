# PPTX load_guide 源工具接线验收（2026-11-15）

来源固定为 GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c 的 slides-skill.ts、packages/pptx-ops/src/prompts/ops。复用此前完整迁入的原始 Markdown，不改写 vendor 文件，不另建桌面工具循环。

## 已接行为

SlidesAIToolkit 注册源名称 load_guide(groups)，Agno schema 的 groups 为必填字符串数组，枚举及顺序为 text、element、insert、table、slide、deck。运行时拒绝空列表、未知名称及非法类型；先验证整个请求，再读取任何指南，输入不能变成任意文件路径。

返回 output 为完整来源原文，多组选取按请求顺序去重，以来源分隔符两个换行、---、两个换行连接；mutated=false。六组原文全部返回时超过 7 万字符，未分页或截断。缺失源文件明确失败，不生成占位指南。加载回执采用本地中文 summary；原生差异放在独立 nativeAdapter 字段，不污染或重写 output。

nativeAdapter 和 planner 指令明确：来源 apply_ops 示例不授予本地操作，原生只能通过注册工具和既有候选 schema 工作；指南不能代替 read_slide 完整授权读取。来源几何为 EMU，原生普通编辑为 96dpi px（1 px=9525 EMU）。备注模式仍只有 notesEdits 权限。所有编辑需引擎预览、用户显式采纳及另行保存。

## 验证证据

首批 20 项契约测试先失败再实现。63 项受影响测试通过（26.48 秒），覆盖六份原文与固定 manifest 的字节数及 SHA256、完整返回、顺序去重、整批验证、缺失文件、无权限副作用、真实 Agno schema 和工具回执、原生服务与 43 技能加载。另 2 项验证来源 apply_ops 无法绕过原生 schema，备注模式在加载指南后仍拒绝画布编辑而允许已读取的备注候选。

真实 PPTX 用例使用 Agno + ScriptedModel，实际执行 load_guide → 授权 read_slide → propose_operations → 引擎预览 → 显式采纳 → 文件重开，验证源内容不变，未授权页面和人工文字、斜体、背景、页序保留，几何及字体实际写入。ScriptedModel 是模型提供方夹具；不计为真实外部模型或生产数据库验收。此为后端文档工具，无前端代码变更，不重复运行前端构建与浏览器。

测试日志：/workspace/scratch/pr245-slides-guides-affected.log、pr245-slides-guides-extra.log。新增测试 test_slides_ai_guides.py，既有真实引擎测试 test_slides_ai_tools.py 同时保留不加载指南和先加载指南两种路径。

## 保留范围

本轮仅完成 load_guide，不据此声称 PPTX 来源 apply_ops、样式模板库、媒体或生成任务已经全部接线；完整一对一对齐继续进行。

备注与 API 专项另 9 项通过（14.13 秒），合计 74 项相关节点分批通过。独立复核未发现 Critical、Important 或 Minor 问题；Ruff、git diff --check 通过。文档沿用远端新的 docs/archive/office-acceptance 归档位置。
