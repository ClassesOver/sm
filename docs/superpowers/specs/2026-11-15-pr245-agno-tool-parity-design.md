# PR #245：Agno 助手与 GenOffice 工具一对一对齐（待确认）

## 目标与依据

用户要求继续 PR #245，AI 助手基于 Agno，与 GenOffice 工具一对一对齐。
代码基线为 PR head `9e6e0f58`；固定上游为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
本文是拟议范围和源码清单，不是对齐完成声明。

## 实施方式

建议采用独立源工具入口 + Agno 原生工具执行 + 现有引擎适配。逐工具核对名称、说明、参数类型、必填项、默认值、返回结果、错误语义和副作用。
已有通用 propose_operations 可以作为内部候选登记能力，但不能代替多个源工具的独立对外契约。
直接移植桌面 AgentLoop 会重复 Agno 执行机制及引入 IPC；仅添加同名包装也不能证明行为对齐，因此不推荐这两种方式。

现有网页授权、冻结草稿、来源身份检查、预览与显式采纳继续复用；文档创建、导航、网络搜索、图片生成各自接真实宿主能力。
创建文档必须返回已登记产物的实际身份，导航必须实际改变当前视图；不使用成功占位回执。
工具返回的业务内容可以采用网页端结构化包装，但须记录与源端文本回执的具体映射及差异，不能把差异标为完全一致。
遵守 AGENTS.md：Agno 已支持的机制优先；新图表使用 Matplotlib；验收失败不阻断已生成且可验证文件的下载。

## 已核实差异

- XLSX 工作簿 Toolkit 注册 11 个源工具，select_range/create_document 未注册；find_cells 缺少 regex；sheetId 使用表名，部分工具缺省使用首表，源端采用稳定 ID 和当前表。
- Word 读取、候选编辑、评论处理分散于不同任务；任务 MCP 当前只注册 get_document_context/read_blocks/search_text/propose_operations，不能视为完整 Word 源工具表。
- PPTX SlidesAIToolkit 当前注册 get_presentation_context/read_slide/propose_operations，尚不能替代源端 17 个 slides-skill 工具。
- PDF 读取、批注、表单分任务注册；源端部分写工具通过本地通用候选操作承接，需逐项明确参数及副作用映射。

## 交付与验证

按 XLSX、Word、PPTX、PDF 分批建立可执行工具契约与实现，每批更新源入口→Agno入口→引擎→专项测试映射。
先补现有工具参数/默认值差异，再补缺失工具及宿主流程；顺序是建议，用户可调整。
测试验证实际 Agno 注册 schema、调用与回执；写入工具验证真实引擎输出、非目标内容保留、预览和显式采纳；导航验证实际视图，创建验证文件身份及重开。
遵守仓库禁止重复完整测试的要求，按受影响范围验证。ScriptedModel 不算真实 provider 验收。
完整目标包括缺失工具的提议尚待用户确认。媒体 provider 和桌面能力的网页对应行为需在相关批次具体设计，未实现的能力保持明确缺口。

## 固定源工具清单

以下只覆盖这四个声明文件；附件、搜索等组合 skill 中的额外工具仍需另行盘点，不能将本清单称为所有可用工具的全集。
源码重新从固定 commit 获取，SHA-256 记录下载原始字节。每行的实施状态初始为待逐项验证，不代表缺少全部底层能力。

### docs（29 项）

源：`apps/docs/src/renderer/ai/tools.ts`

SHA-256：`33a8f21c62b07ec1cbf4021bd58077ad1a71ce58df4d9a3c2341d23e665c7409`

| 源工具 | 当前核验状态 |
| --- | --- |
| `get_document_context` | 待逐项验证契约与运行链 |
| `read_blocks` | 待逐项验证契约与运行链 |
| `insert_content` | 待逐项验证契约与运行链 |
| `write_document` | 待逐项验证契约与运行链 |
| `replace_blocks` | 待逐项验证契约与运行链 |
| `replace_selection` | 待逐项验证契约与运行链 |
| `apply_ops` | 待逐项验证契约与运行链 |
| `read_revisions` | 待逐项验证契约与运行链 |
| `accept_changes` | 待逐项验证契约与运行链 |
| `reject_changes` | 待逐项验证契约与运行链 |
| `read_comments` | 待逐项验证契约与运行链 |
| `reply_comment` | 待逐项验证契约与运行链 |
| `resolve_comment` | 待逐项验证契约与运行链 |
| `insert_footnote` | 待逐项验证契约与运行链 |
| `insert_endnote` | 待逐项验证契约与运行链 |
| `delete_note` | 待逐项验证契约与运行链 |
| `edit_note` | 待逐项验证契约与运行链 |
| `read_notes` | 待逐项验证契约与运行链 |
| `add_comment` | 待逐项验证契约与运行链 |
| `delete_comment` | 待逐项验证契约与运行链 |
| `web_search` | 待逐项验证契约与运行链 |
| `image_search` | 待逐项验证契约与运行链 |
| `analyze_media` | 待逐项验证契约与运行链 |
| `insert_image` | 待逐项验证契约与运行链 |
| `generate_image` | 待逐项验证契约与运行链 |
| `insert_chart` | 待逐项验证契约与运行链 |
| `edit_chart` | 待逐项验证契约与运行链 |
| `set_header_footer` | 待逐项验证契约与运行链 |
| `create_document` | 待逐项验证契约与运行链 |

### sheets（13 项）

源：`apps/sheets/src/renderer/ai/tools.ts`

SHA-256：`c794acbe7fc856308c5c5e97c246166137a3bd2bc35b575cb290d11bc6ec5e8f`

| 源工具 | 当前核验状态 |
| --- | --- |
| `get_workbook_context` | 待逐项验证契约与运行链 |
| `read_range` | 待逐项验证契约与运行链 |
| `aggregate_range` | 待逐项验证契约与运行链 |
| `load_guide` | 待逐项验证契约与运行链 |
| `read_formats` | 待逐项验证契约与运行链 |
| `read_sheet_features` | 待逐项验证契约与运行链 |
| `read_cells` | 待逐项验证契约与运行链 |
| `find_cells` | 待逐项验证契约与运行链 |
| `select_range` | 待逐项验证契约与运行链 |
| `trace_precedents` | 待逐项验证契约与运行链 |
| `trace_dependents` | 待逐项验证契约与运行链 |
| `propose_operations` | 待逐项验证契约与运行链 |
| `create_document` | 待逐项验证契约与运行链 |

### slides（17 项）

源：`apps/slides/src/renderer/ai/slides-skill.ts`

SHA-256：`d55386ed080794b922895c39a6552e474a15e66ffee4f5f7c044f760e1ec6336`

| 源工具 | 当前核验状态 |
| --- | --- |
| `read_slide` | 待逐项验证契约与运行链 |
| `execute_slide_script` | 待逐项验证契约与运行链 |
| `web_search` | 待逐项验证契约与运行链 |
| `image_search` | 待逐项验证契约与运行链 |
| `generate_image` | 待逐项验证契约与运行链 |
| `analyze_media` | 待逐项验证契约与运行链 |
| `insert_web_image` | 待逐项验证契约与运行链 |
| `replace_image` | 待逐项验证契约与运行链 |
| `ask_clarification` | 待逐项验证契约与运行链 |
| `plan_deck` | 待逐项验证契约与运行链 |
| `regenerate_slide` | 待逐项验证契约与运行链 |
| `generate_deck` | 待逐项验证契约与运行链 |
| `save_style_template` | 待逐项验证契约与运行链 |
| `list_style_templates` | 待逐项验证契约与运行链 |
| `edit_chart` | 待逐项验证契约与运行链 |
| `apply_ops` | 待逐项验证契约与运行链 |
| `load_guide` | 待逐项验证契约与运行链 |

### pdf（45 项）

源：`apps/pdf/src/renderer/ai/tools.ts`

SHA-256：`904dd44062334ba1a0df87b06ed9d2dc057e2fa9f6334d04ca998f9d4462acfe`

| 源工具 | 当前核验状态 |
| --- | --- |
| `read_pages` | 待逐项验证契约与运行链 |
| `search_text` | 待逐项验证契约与运行链 |
| `goto_page` | 待逐项验证契约与运行链 |
| `markup_text` | 待逐项验证契约与运行链 |
| `read_annotations` | 待逐项验证契约与运行链 |
| `add_note` | 待逐项验证契约与运行链 |
| `reply_note` | 待逐项验证契约与运行链 |
| `edit_note` | 待逐项验证契约与运行链 |
| `delete_markup` | 待逐项验证契约与运行链 |
| `delete_note` | 待逐项验证契约与运行链 |
| `edit_text` | 待逐项验证契约与运行链 |
| `edit_block` | 待逐项验证契约与运行链 |
| `move_text_block` | 待逐项验证契约与运行链 |
| `insert_text` | 待逐项验证契约与运行链 |
| `add_form_mark` | 待逐项验证契约与运行链 |
| `list_inserted_text` | 待逐项验证契约与运行链 |
| `edit_inserted_text` | 待逐项验证契约与运行链 |
| `move_inserted_text` | 待逐项验证契约与运行链 |
| `delete_inserted_text` | 待逐项验证契约与运行链 |
| `image_search` | 待逐项验证契约与运行链 |
| `generate_image` | 待逐项验证契约与运行链 |
| `list_page_images` | 待逐项验证契约与运行链 |
| `insert_image` | 待逐项验证契约与运行链 |
| `transform_image` | 待逐项验证契约与运行链 |
| `rotate_image` | 待逐项验证契约与运行链 |
| `replace_image` | 待逐项验证契约与运行链 |
| `flip_image` | 待逐项验证契约与运行链 |
| `set_image_opacity` | 待逐项验证契约与运行链 |
| `crop_image` | 待逐项验证契约与运行链 |
| `remove_image_background` | 待逐项验证契约与运行链 |
| `delete_image` | 待逐项验证契约与运行链 |
| `list_form_fields` | 待逐项验证契约与运行链 |
| `apply_ops` | 待逐项验证契约与运行链 |
| `insert_blank_page` | 待逐项验证契约与运行链 |
| `set_page_size` | 待逐项验证契约与运行链 |
| `crop_pages` | 待逐项验证契约与运行链 |
| `extract_pages` | 待逐项验证契约与运行链 |
| `split_pdf` | 待逐项验证契约与运行链 |
| `split_pages` | 待逐项验证契约与运行链 |
| `merge_pages` | 待逐项验证契约与运行链 |
| `replace_pages` | 待逐项验证契约与运行链 |
| `get_outline` | 待逐项验证契约与运行链 |
| `set_watermark` | 待逐项验证契约与运行链 |
| `set_header_footer` | 待逐项验证契约与运行链 |
| `create_document` | 待逐项验证契约与运行链 |
