# PPTX AI 整稿阅读演讲者备注

2026-11-11；延续 PR #218。固定 GenOffice 对齐源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 行为

复用已有 `pptx-engine/src/notes.ts::getSlideNotes` 和 `inspectSlideNotes` 的真实正文提取，不新增 writer 或模型调用循环。整稿授权时，非空 `notesText` 作为 `type=speakerNotes` 资料进入同页冻结 JSON；对象选区不附带任何备注。即使备注只读，仍可读取已成功提取的文字。

目录仅提供 hasSpeakerNotes，不计阅读。完整分页读完正文和备注后，该页才可引用；只有备注的页面也计入范围。引用通过 `speakerNotes=true` 和“演讲者备注”标签标识，不伪造画布 elementId。备注正文继续按资料处理，不能授予工具、写入或角色权限。

前端明确提示整稿包含备注、对象选区不含备注，并纠正旧的“只读文字、不读表格图表”说明。沿用已有快照/取消/来源检查；阅读不会采纳、保存或导出。

## 本轮验证

- `test_native_slides_read_ai.py`：新增后19项通过；独立审查后追加混合分页和真实格式化只读备注两项，各自通过，最终21项均通过。覆盖 notes-only、60000字符冻结分页、同页选区隔离、实际格式化只读备注、正文已读而末尾备注未读不得引用。
- 真实引擎人工备注草稿经过 NativeOfficeReadService → 实际 Agno ScriptedModel，工具回执读取“人工备注59”；来源仍为“原备注42”，source/effective SHA 不同，引用标注备注且没有写操作。源备注由 python-pptx 独立读取确认。
- `test_native_office_read_tasks.py` / `test_native_office_read_api.py` 共18项通过，保留身份重绑、取消、来源变化、HTTP授权及SSE契约。
- `native-office-assistant.test.ts` 8项通过，含新提示、备注引用和只读草稿保持。
- 完整 `tsc --noEmit`（Node heap 4 GiB）通过。补齐最新lock依赖后，修正两个既有测试夹具的重复字段和不成立的泛型mock，两个文件23项通过；没有弱化产品类型或测试断言。默认2 GiB曾内存不足，不记通过。
- 最终 Vite 50.16秒通过，全部JS预算通过，不提高上限。日志 `/tmp/office-notes-pdf-font-vite-final.log`、`/tmp/office-notes-pdf-font-budget-final.log`；实际CSS/JS纳入最终PDF字体改动。
- 真实 Chromium 140.0.7339.16：`/tmp/office-notes-read-browser-20261111-final3/summary.json` 的 ok=true，XLSX/PPTX两条真实HTTP/授权/Agno只读整稿链通过；18份实际加载JS逐一核磁盘SHA，manifest前后不变，页面/控制台/HTTP错误为空。PPTX工具实际读取备注，下季度目标59进入回答并具有备注引用；原件和localStorage草稿不变，无preview/save/export请求。root独立重核清单、文件身份及实际文字布局，并目视最终PPTX截图。
- 首次smoke的旧入口文案断言与最新“AI助手”入口不一致，已按真实可访问标签修正。随后发现真实侧栏正文不可见：dock硬编码sans-serif覆盖宿主中文字体栈，在此环境的通用字体解析下正文height=0。改为继承宿主字体、保留12px/1.5；最终浏览器断言可见正文height>0且font-family等于宿主，XLSX/PPTX均通过。失败截图与诊断留在同名前缀的早期目录，未以textContent替代innerText掩盖问题。

## 边界

仅包含引擎成功提取的备注正文，不代表备注页母版、页眉页脚、图片视觉或复杂内容完整还原。未扩大对象选区授权，未增加单独备注选区入口。浏览器本轮验证关闭编辑时的整稿阅读；实际未保存备注草稿与对象选区隔离由真实引擎/服务专项证明，不能合称为同一浏览器场景。真实模型和生产数据库整链未在本轮验收；ScriptedModel 不算真实 provider。
