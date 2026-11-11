# 原生 Office AI 真实 Provider 验收

日期：2026-11-11。模型使用 AgentSettings.from_environment() 与生产 _report_model → _reporting_phase_model、同 thinking profile/预算及模型参数；未替换 endpoint 或模型。实际模型 ID 为 deepseek-v4.1-flash。全部输入为现场生成的合成文件，不包含用户业务资料；不提交、推送或部署。

## 当前结果与边界

| 格式 | 当前真实结果 | 证据 |
| --- | --- | --- |
| PDF 只读 | 已通过真实模型 → 四工具声明的 Agno 阅读循环 → PDFium；实际调用 read_pages/read_annotations，两页完整读取、双页来源引用、42+17=59 million，issues为空，原始内容未改。 | /tmp/native-pdf-provider-fixed-20261111.json，4.29秒；详细见 NATIVE_PDF_AI_READ_ACCEPTANCE.md。 |
| PDF 处理批注 | 新增真实模型 → create_native_pdf_review_planner → NativePDFReviewService/NativeEditorService → 实际混合预览 → 显式 accept；pypdf 独立回读 Amount due 700、未选文字保持、精确原父线程的 /T=AI Assistant 回复，源文件 SHA 不变。 | /tmp/native-pdf-review-real-provider-20261111.json，9.15秒；真实生产模型工厂 deepseek-v4.1-flash，合成单页人类便签，作用域隔离内存仓储，非生产DB或浏览器直连provider。 |
| Word 文字候选 | 已通过真实模型 → create_native_ai_service → 原生编辑器预览 → 显式 accept → 实际 DOCX 引擎；python-docx 独立回读“已核验”，未选择段落保持原文，原始来源未改。 | /tmp/native-office-edits-provider-fixed-20261111.json，docx记录6.71秒。 |
| PPTX 文字候选 | 已通过真实模型 → create_native_slides_ai_service → 原生编辑器预览 → 显式 accept → 实际 PPTX 引擎；python-pptx 独立回读“已核验”，原始来源未改。 | 同上，pptx记录3.28秒。 |
| XLSX 单格候选 | 已通过真实模型 → create_native_workbook_ai_service → 原生编辑器与引擎候选预览 → 显式 accept。修复后 writeValue=true、cell.value=59；openpyxl 独立回读 A1 为数值59、B1 保留 Untouched，原始来源未改。 | /tmp/xlsx-native-ai-provider-root-20261111.json，3.87秒；失败历史保留，不用确定性 planner 的浏览器成功替代。 |

Word/PPTX 使用真实签名会话、工作区、NativeEditorService 与结构化 planner，但仓储是按上下文隔离的内存夹具；没有生产 DB、浏览器直连真实 provider、实际修订保存/下载的端到端证明。本次仅验证合成来源上的单次文字/单格候选，不证明所有源工具、媒体、复杂来源、历史/流式进度及长期任务都已对齐。原始空草稿 PDF provider 成功也不能替代未保存草稿的实际 provider 证明。

## 故障与修复证据

- PDF 首轮 /tmp/native-office-real-provider-20261111.json 为失败。安全诊断确认模型实际已读取两页但返回 Markdown，直接 Agent 绕过生产 JSON_OBJECT 能力策略，最终 model_type 校验失败。修复复用 VerifiedModelCapabilityResolver 协商，保留真实工具和每任务模型副本；协议专项 RED→GREEN，真实复验成功。Agno 中间一次解析 warning 保留，不声称零告警。
- 三格式首轮 /tmp/native-office-edits-provider-20261111.json 保留失败。Word/PPTX 因探针误将 PDF 字节预览当作原生文件读回而失败，修正诊断脚本后成功，没有为探针错误修改产品；XLSX 首两轮真实失败，实际输出 writeValue=59；原生 prompt 未明确该字段是布尔写入标志。复用既有明确语义及完整 arguments.edits 示例补足 true 与 cell.value 的区分，保持引擎严格拒绝非布尔值，不做静默强转；两项专项 RED→GREEN 后真实复验成功。
- 修正版探针 /tmp/probe-native-office-edits-provider-fixed-20261111.py 保存实际模型结构化输出、显式采纳操作及有效文件 SHA；本文件不包含密钥、请求头或完整模型 endpoint。

- 另一使用 uv --env-file 的 XLSX 探针在候选生成前收到403 AccessDenied.Unpurchased（/tmp/xlsx-native-ai-provider-20261111.json）。该失败保留，不归因产品代码；以与前述已通过探针一致的 PYTHONPATH=. .venv/bin/python 启动生产 settings/model factory 后才获得本表成功证据，未擅自更换模型。

## 新增批注任务真实模型证据

2026-11-11 探针 /tmp/probe-native-pdf-review-real-provider-20261111.py 通过同一生产 settings/model factory，实际读取完整一页及全部一条批注。完整任务返回 replaceText/replyNote 候选，服务实际预览与显式采纳后独立回读正文700、未选择原文和AI作者；/tmp/native-pdf-review-real-provider-20261111-xww9zoiy/{source.pdf,accepted-preview.pdf} 保留实际字节。root另独立核对source/output SHA及回复 /IRT 精确指向原始根便签。

本次 provider 运行发生于 PDF 引擎“直接字典与字符串转义兼容”构建，后续间接对象身份遍历的最终桥以七项真实引擎回归及最终浏览器另证；不把模型调用时间跨写为后续最终桥重新调用。保留一次 Agno中间 cleaned JSON 解析 warning；最终结构化任务、真实预览与采纳成功，不声称零告警。此探针未执行修订保存/下载，不能替代实际保存链或全部PDF AI工具面验收。
