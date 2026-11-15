# Word GenOffice 对齐增量（2026-11-14）

固定源：`f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批不是完整Word等价性声明，不给完成百分比。

已实现：Editor与22语言翻译预设（候选明确采纳）、简单正文修订范围、实时文本比较、只读摘要提示、HTML与Markdown导出；4主题／6字体／6颜色预设；源PNG与向量墨迹；文档保护启停；文本框、109形状、12艺术字插入；柱／折／饼图及限定已有图表数据编辑；DATE/TIME/PAGE/NUMPAGES/FILENAME域及F9更新；页眉页脚、脚注尾注的可信简单增删修订；可信整块图片的尺寸、旋转、翻转、环绕、对齐与位置；同普通单元格连续段落格式及表格后插入普通段落。

## 验证与证据

- 完整TypeScript检查与隔离生产构建通过。构建 `/tmp/word-genoffice-integrated-build`，487个JS分包通过既有预算；Word主分包251778字节，限额256000，未放宽阈值。
- 最新前端定向7文件94测试通过，日志 `/tmp/word-all-related-tests.log`。宿主新增对象、主题、保护、墨迹与story来源17测试通过，日志 `/tmp/word-final-new-host.log`。其他专项结果见各模块测试及下方验收，不将不同批次数字相加冒充全套测试。
- Editor／翻译候选→明确采纳→真实HTTP保存→下载→重开见 [预设与比较验收](NATIVE_WORD_REVIEW_PRESETS_COMPARE_ACCEPTANCE_20261114.md)。真实Agno工具链使用ScriptedModel，不是真实生产模型评估。
- 文本框＋Facet主题＋墨迹实际保存修订2，保护保存修订3，解除保护保存修订4。原始证据 `/tmp/word-families-20261114-final` 与续接 `/tmp/word-families-20261114-resume`；续接复用已保存文件SHA，只执行解除保护一次保存。独立ZIP/lxml/python-docx回读通过，181资源身份匹配，窄屏截图已保留。HTML与Markdown真实下载通过。
- 表格后新增空／普通段落的6个真实DOCX测试通过；ZIP目录项与顺序不视为内容变更，严格验证core仅正常更新修订号和修改时间，app及其他部件字节保全。图表／域与story的11个bridge测试通过（`/tmp/word-final-chart-story-bridge.log`）。
- 此HTTP测试使用真实FastAPI授权、工作区、发布与下载链，仓储为限定内存fixture，不等同生产数据库验收。业务审核仍可报告native_source_review_pending，不阻断已签发下载。
- 浏览器使用已有canvas-fontconfig.conf；默认环境系统字体测得零宽／零墨迹，不能据此判断Word渲染错误。预检、原始失败和成功证据均保留。

## 仍有限制

保护启用后本地正文统一只读，尚未按comments／trackedChanges／forms精细开放；全文件加密不含。复杂move／属性／文本框修订、完整Review Pane、批注AI批量改写、邮件合并、源完整打印宿主、图片层级及组合对象、已保存形状／文本框富编辑仍缺。图表保持固定源同结构写入边界，不能任意改变已有图表系列形状。图片仅可信整块来源，媒体字节不变。Story、图表／域、图片格式和保护转换要求独立保存，避免混合操作丢失。FILENAME使用本地公开下载名report.docx，不声称保留原上传文件名。

顶层多段段落对话框原本已有，本批补混合单位及身份过期保护；固定源图片Ribbon无颜色／透明度入口，移除了本地无源占位。各项不因按钮启用即算完整闭环；后续浏览器专项证据追加于此。

## 图片格式最终浏览器专项

`/tmp/word-picture-format-20261114/result.json` 通过，181个真实JS/CSS响应SHA与构建磁盘一致，pageerror为空。真实python-docx图片fixture含原生xfrm；浏览器旋转90度与水平翻转后唯一formatImage操作保存修订2，下载SHA `8d52c7c54db4153e11e559df4d5c62fd71ad2f5b316d4655f8abd791fb028aff`，重开CSS及独立OOXML一致。仅document.xml改变，媒体和其他部件、邻近段落、页眉页脚保全。业务审核仍pending，不声称版式审核通过。

## 审查修复与未计通过的运行

最新四族独立代码审查发现已有图表缺省系列名产生undefined导致NativeDraft拒绝，已改为省略缺省属性；真实modal→修改→NativeDraft序列化专项通过。域浏览器初轮虽签发修订，但操作为空，未计为插入成功；诊断确认普通单栏不创建多栏缓存，已改为复用真实分页测量，并复核异步等待期间文档与选区。原始失败记录保留在 `/tmp/word-chart-fields-http-20261114-absolute`；已成功图表修订不重复保存。

修复后最终构建 `/tmp/word-genoffice-final-reviewed-build` 完整TypeScript与Vite通过，487个JS分包仍全部通过原预算，Word主分包252247字节。早先图片/图表浏览器证据对应integrated构建，不冒称在修复后构建重复保存。

## 图表与PAGE最终浏览器专项

图表真实保存／下载／重开在 `/tmp/word-chart-fields-http-20261114-absolute`；离线 `chart-independent.json` 核验标题HTTP Chart Revenue、系列数值12345和嵌入XLSX，未重复保存图表。

修复版域续测 `/tmp/word-chart-fields-http-20261114-field-range-final/result.json` 通过：181真实资源SHA匹配、页面异常为空、只保存一次。第一段UTF16位置3插入PAGE，独立XML回读为“本季度1收入42”且instrText为PAGE；图表、嵌入工作簿、关系、页眉页脚及全部非document部件字节保全。此fixture从已保存图表文件重导入，实际保存为新fixture修订2，文件历史名inline-field-r3.docx不作为修订号依据。此前空保存及定位错误均未计域通过，也未重做成功的图表保存。
