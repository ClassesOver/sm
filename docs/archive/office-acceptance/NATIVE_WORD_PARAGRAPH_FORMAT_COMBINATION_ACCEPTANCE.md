# Word 同段落边框与底纹组合验收

固定源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。`Ribbon.tsx` 的 `applyHomeBorders` 调用 `setParaAttr({ borders })`，底纹调用 `setParaAttr({ shadingFill })`，二者独立。

本批只允许同一来源段落各一个 `setParagraphBorders` 与 `setParagraphShading` 组合。前端 diff 和草稿恢复校验完整节点，只豁免这两个属性；后端保留原始 hash 与字段白名单，再在当前保存 XML 上依次修改 `shd`、`pBdr`。重复操作、正文、样式、分页、布局或注释混编仍拒绝。主题色、非单实线等未支持源属性保留原限制。

只读回归额外发现旧有底纹、边框操作缺少服务端 documentProtection 检查；本批仅修正这两项。新增独立 `paragraphShadingEditable`、`paragraphBordersEditable`，受保护源在 inspect、Ribbon、命令、diff、草稿恢复和实际写入时保持一致；不改变其他操作能力。

这两个能力 flag 也复用现有 `paragraphShadingXml`、`paragraphBordersXml` 的纯字符串补丁函数检查复杂源可写性，丢弃输出，不修改 block 或 ZIP。真实图案底纹、double 边框分别关闭对应能力，对方能力及全局 editable 保持原值。直接 inspect 桥接实测源文件字节、mtime、inode 不变，即使请求提供 output 路径也不创建输出文件；flag 保持布尔字段。

验证证据：

- RED：前端原实现三项组合失败；ZIP 六项组合以 batch conflict 失败。只读探针原本允许写受保护文档；新增能力探针在原实现失败，随后修复。
- 前端相关四文件 32 项通过，涵盖组合两种顺序、独立撤销、重做、auto/none、边框清除、草稿恢复、字段与身份伪造、重复、只读和原 Ribbon 路由。另测重复来源锚点不因只读能力过滤而被隐藏。
- ZIP 新增原九项通过（六种顺序/底纹变体、负向混编、两种未支持源）；新增保护测试验证组合和两项单独写入均拒绝。相关既有底纹/边框九项通过。ZIP 只比较真实文件部件，忽略重打包目录条目；仅 document.xml 变化，原正文 rPr、keepNext 和其他段落保持不变。
- 真实 Chromium 140，`DOCX_INSERT_CASE=paragraph-format-combination`、端口4194：先底纹后边框，刷新草稿，撤销重做，保存下载修订2；重开后先边框后底纹，保存修订3；重开后同时清除，保存修订4并重开。三次真实 Python patch_docx，独立 XML 回读通过，非 document 部件 SHA、正文、直接 rPr、keepNext 全保留，pageErrors=[]。
- 真实 Chromium 保护样本：底纹按钮/色板、边框按钮/菜单四项 disabled，无保存请求，pageErrors=[]。
- TypeScript `tsc --noEmit` 退出0。根任务最终统一 build 退出0（Vite37.49s），budget 与 contract 均退出0；随后端口4194顺序完成组合、保护两个 built preview，均退出0，pageErrors=[]。组合包含三次真实保存、下载、清除及最终重开，保护样本四个控制禁用。所有实际加载 JS 响应200且 SHA256 对照当前静态构建文件一致：Word入口 `lazy-docx-main-umqu0fnf.js` / `33820de1724f4d79f1e3af4eaa34ee8470961dc72c3cd768dc209d9dfa6caa48`；引擎 `lazy-native-docx-engine-DsROsJBD.js` / `29e787ebfd5fe24856ad8b1d9a5eadc96cbb2ca04e8b2f9d7711f39c42af35a6`。4194端口已确认无监听。

日志：`/tmp/word-paragraph-combo-front-capability-green.log`、`/tmp/word-paragraph-combo-zip-green2.log`、`/tmp/word-paragraph-combo-inspect-green.log`、`/tmp/word-paragraph-combo-gui3.log`、`/tmp/word-paragraph-combo-protected-gui.log`、`/tmp/word-paragraph-combo-tsc-final2.log`。

最终构建浏览器日志：`/tmp/word-paragraph-combo-built-preview-final.log`、`/tmp/word-paragraph-combo-protected-built-preview-final.log`。复杂源与无写入探针：`/tmp/word-paragraph-combo-complex-green.log`、`/tmp/word-paragraph-combo-inspect-no-write.log`。

边界：本批不放开与同段正文、行内格式、布局、样式或注释的组合，也不宣称全部 Word 功能对齐。不修改发布签发链路，不执行完整套件、提交或推送。
