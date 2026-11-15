# PPTX 固定表格预设与选项

固定原始来源 `genspark-ai/genoffice@f8c17004fb730df11f0f743164ffd8b4281bb38c`，本地完整 Git 身份见 `/workspace/genoffice`。2026-11-10。

## 原始材料与适配语义

原 Ribbon.tsx:360–405 列出8种预设，2661起调用 styleName 和 firstRow/bandRow/rtl；style-actions.ts:312 接 IPC；packages/pptx-ops/src/ops/table-ops.ts:247 起解析 TABLE_STYLE_PRESETS。预设通过固定 editTableStyle 的 tblPrXml/clearDirectFormatting 及 ensureTableStylePart 写入 OOXML，原引擎未修改。

Web Table Design 使用同一8项名称的选择器和三个源开关，属于宿主交互适配。协议 tableStyles 沿用来源页/对象ID，扩展 styleName 和布尔 firstRow,lastRow,firstCol,lastCol,bandRow,bandCol,rtl。后四项未新增源Ribbon不存在的UI。

一个草稿项表达多次源命令的最终结果：先应用预设，再应用显式区域/方向开关，最后底纹/边框覆盖。选择新预设清此前颜色/边框/区域覆盖；rtl 是独立状态，按固定helper保留。来源flags由实际表格读取，false不丢失。none/lightGrid/fullBorder共用NO_STYLE GUID，来源检查不凭GUID猜测这三项；重开时可保持未命名的现有样式。选择器未冒充源缩略卡片预览。

预设按原实现清除单元格直接填充/边框，以便样式生效，保留txBody、字体、几何、合并标记和非样式对象。不是任意内置GUID选择或自定义样式XML入口。

## 来源保护

原 ensureTableStyleXml 仅用字符串包含判断样式存在，因此桥接必须核对规范样式表和固定ID定义；同ID不同定义、复杂/不明XML或关系不能静默覆盖。样式表的创建需连同 Content Types 与 presentation relationship 验证。与同表结构操作的冲突沿用既有边界。

预设以来源可编辑性为准；草稿历史、刷新恢复、画布服务端渲染、保存下载与重开都须验证。整体表格/Office/生产、桌面与完整镜像验收不由本功能代表，功能开关保持关闭。

## 验证记录

- 后端26项新增+4项相关既有检查通过，涵盖全部8预设、无样式部件创建/关系/Content Types、双表、幂等、覆盖顺序、RTL、纯flags不清直接格式、其他样式定义保留，以及11类危险来源与非空单元格扩展反例。日志 `/workspace/scratch/pr210-table-presets/`。
- 前端20项新测试+26项结构+24项Ribbon+1项底纹回归通过。来源flags、false覆盖、preset/RTL顺序、草稿恢复、锁定/冲突/失效回调均有检查。
- 独立 LibreOfficeDev 26.8.0.0.alpha0 消费8页实际PPTX并导出PDF；pypdf验证每页名称、全部格文字与其他文本，pdftoppm/Pillow验证8组表头/交错填充RGB及网格。证据 `/workspace/scratch/pr210-presets-pending/external/independent-acceptance.json`；此为独立消费者互操作证据，不等于PowerPoint桌面全验收。
- Node22 --network=none打包引擎实际输出8预设；独立python-pptx/ZIP回读文字与五个固定定义，非法preset非零退出且无产物。证据 `pr210-presets-pending/offline/independent.json`。

源能力保守边界：canonical a:tblStyleLst、固定定义逐字节匹配、标准命名空间与唯一规范rId、tblPr只支持已确认bool属性及单个styleId；非空tcPr extLst拒绝，空extLst保留。即便语义等价的换前缀/重排样式定义也可能只读，不冒称全格式兼容。

生产静态 Chromium 表格预设闭环通过：预设清旧底纹、RTL保留、false覆盖、历史/刷新、真实画布颜色、保存下载与重开，独立python-pptx验证文字/合并/标记。证据 `pr210-presets-pending/pptx-browser/evidence.json`。

**已确认的外部差异**：额外把浏览器RTL产物交给当前LibreOffice消费，列未被镜像；同一文件在固定native render-tree的列X顺序已镜像、OOXML rtl=1持久化。保留PPTX/PDF/词坐标与失败结果 `pr210-presets-pending/external-rtl/independent.json`，不标记跨软件RTL视觉验收通过，也不因此丢弃可读产物。此差异尚待其他Office消费者确认。

Standard/Slides生产构建、完整前端TypeScript、配置的Standard budget、Python应用Ruff和diff检查通过；未重复完整仓库测试。所有原始vendored引擎保持不变。首轮构建曾读到正在修复的新测试TS断言而退出，修复后最终构建通过；不隐藏该过程或声称跨软件RTL验收已通过。
