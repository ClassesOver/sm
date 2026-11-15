# XLSX 页面布局 ▸ 主题 / 颜色 / 字体验收

2026-11-12。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这一项功能闭环，不代表 XLSX Ribbon 已全部对齐。

## 固定源行为

- `apps/sheets/src/renderer/ExcelShell.tsx` 页面布局 ▸ 主题组：Themes 大菜单（`THEME_PRESETS`）、Colors 与 Fonts 两个 MenuSelect；选中即应用，没有“主题效果”。
- `apps/sheets/src/renderer/themes.ts`（SHA-256 `42f527e0…afc04f23`）：8 套配色、6 套字体、8 个预设主题（配色与字体按 `FONT_BY_THEME` 配对）。配色按主题索引顺序 `[lt1, dk1, lt2, dk2, accent1-6, hlink, folHlink]` 存放。
- `page-layout-actions.ts` 的 `case 'theme' | 'theme-colors' | 'theme-fonts'`：
  - 没有主题部件时提示 `appThemeNeedsThemePart`。
  - 主题没有可改写的 fontScheme 时，“字体”不可用，“主题”只换配色，以免后续保存失败。
  - 写入引擎 `setThemePart`（来自固定源 `xlsx-theme.ts`），原位改写 `xl/theme/theme1.xml` 的 `<a:clrScheme>`、`<a:fontScheme>` 及其名称。引用主题槽位的样式随之改色，显式 RGB 不变。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 预设数据 | `frontend/src/workbook-vendor/core/themes.ts`：固定源 `themes.ts` 的接口、`scheme`、`COLOR_SCHEMES`、`FONT_SCHEMES`、`FONT_BY_THEME`、`THEME_PRESETS` 原样保留。未复制渲染端的 `applyTint`/`rethemeStyles`（依赖桌面类型）。已登记到 `workbook-vendor/SOURCE.md` 与 `LOCAL-ADAPTATIONS-SHA256.json`。 |
| 操作 | `{kind:'setThemePart', themePath:'xl/theme/theme1.xml', state:{colors?:{name, values[12]}, fonts?:{name, major, minor}}}`。后端（桥接与 Python 允许字段）原已存在，前端此前未接通。 |
| 桥接校验 | `bridge/operations.ts` 新增 zod 严格校验。此前 `themePath` 可为任意部件，现只允许 `xl/theme/theme1.xml`。配色须为 12 个 `#RRGGBB`；名称与字体名不得为空、不得含控制字符、最多 100 字符；不接受多余字段；配色与字体至少有一项。 |
| 前端 | `workbook-theme.ts` 从实际主题部件字节读取可用性和当前名称，判定条件与引擎前置条件一致（12 个配色槽位齐全；major/minor latin 齐全）。生成写入操作的方式与固定源相同。功能区主题组改为三个菜单（主题 / 颜色 / 字体），选中即应用，菜单回弹到标题；标题提示当前名称或不可用原因。“主题效果”保持禁用，原因写为“固定源未提供主题效果写入”。 |
| 预览与历史 | 沿用“允许编辑区域”的整批重放模式：当前操作加上主题操作，在浏览器内真实引擎重放后重建模型，失败则回滚。引用主题色或主题字体的单元格与重开后的结果一致。写入草稿历史，可用文件 ▸ 撤销/重做，刷新后恢复。 |

## 证据

- `reporting/workbook_engine/bridge/theme.test.ts`（2 项）：
  - 在带 Office 默认主题的工作簿上改写配色与字体，读取侧 `themePalette` 解析为新配色，其余部件字节不变；只改字体时配色保持。
  - 以下情况在写入前拒绝：没有主题部件、其他部件路径、`theme2.xml`、空 state、11 个颜色、非法颜色、空名称、含换行的字体名、多余字段。
- `reporting/tests/test_native_xlsx_theme.py`（7 项）：openpyxl 生成的真实工作簿经 Python 原生入口写入。
  - 只有 `xl/theme/theme1.xml` 变化。
  - 单元格仍引用主题槽位（字体 theme=4、填充 theme=5），显式 RGB 不变。
  - `inspect_office` 的 `themePalette` 为新配色。
  - 只改字体时配色保持；5 种非法操作被拒绝。
- `frontend/src/workbook-theme.test.ts`（4 项，含读取失败时降级为不可用而不阻断加载）：可用性与名称读取；三类命令的预设载荷与固定源一致；无字体方案时的降级；三个菜单的派发、回弹、标题与禁用原因；“主题效果”的禁用原因。与 `workbook-ribbon.test.ts` 合跑共 55 项通过。
- `frontend/smoke/workbook-theme-gui-smoke.mjs`：在 Chromium 中跑真实 Python→XLSX 引擎链路，开发服务器模式，授权与修订路由用 fixture。
  - 依次应用：主题 Ember（配色加 Trebuchet MS）→ 颜色 Forest → 文件 ▸ 撤销/重做 → 字体 Georgia → 刷新后草稿恢复，菜单标题显示 Forest / Georgia。
  - 保存为修订 2，下载字节与保存一致。
  - openpyxl/ZIP 独立回读：
    - clrScheme 为 Forest（accent1 `217346`、accent2 `4EA72E`），fontScheme 为 Georgia（major/minor 都是 Georgia）。
    - A1 仍引用主题槽位，B1 显式 RGB 与 A2 数值不变。
    - 改动的文件只有 `xl/theme/theme1.xml`。
  - 重开修订 2 后菜单显示 Forest。
  - 截图中 A1 按 Forest 配色重新着色，B1 不变。

- 基线对比：在 `src/workbook` 上与未改动的 `d50b1369` 逐条比对失败用例名，双方都是 119 个失败（上游已知的 `__getInjector` 等），没有新增。
  - 比对中途发现一处真实回归：工作簿加载时读取主题部件，如果抛错（`workbook-print-routing.test.ts` 的引擎替身没有 `has`）会连带整个加载失败。
  - 已改为读取失败只让主题菜单不可用并说明原因，该文件恢复 2/2 通过。

## 与固定源的差异 / 未验收

- 固定源在渲染端用 `rethemeStyles` 即时重新着色；这里改为在浏览器内真实引擎重放，结果与重开一致，但每次应用需要一次重放。
- 固定源在网格之外（图表、条件格式）要等保存重开才跟随新主题；这里重放后即生效，没有逐项核对图表像素。
- 本地未提供自定义配色或字体编辑（固定源同样没有）。
- 生产构建、真实授权与发布链路未验收，也没有用 Excel 人工打开核对。
