# Word 插入图片 / XLSX 快速填充验收（2026-11-09）

固定 GenOffice 来源：`f8c17004fb730df11f0f743164ffd8b4281bb38c`。基线为更新后的 `code`（`7ef25eb1`）。本轮仅覆盖下述范围，完整功能对齐仍未完成。

## Word：插入本地图片

- 对照固定源 `ribbon-insert-tab.tsx` 的 `insertImageViaDialog` 和 `ribbon-tabs.tsx:399` 的 `insertImageFromDataUrl`，将插入页签的图片按钮接到浏览器文件选择器。
- PNG/JPEG、最大 8MB；按源 620px 最大显示宽度等比缩放，不放大小图。复用既有 `insertParagraphImage`、后端资源关系和内联 drawing 写入，无新增图片 writer。
- 仅开放正文段落的折叠光标，表格内及对象/跨段选区禁用。段中插入沿用拆段锚点规则；一次事务可撤销/重做；操作可回放为草稿。
- 文件对话框打开时捕获文档和选区，解码完成时再次校验；文档/选区改变、只读/保存锁、销毁均拒绝迟到的图片写入。剪贴板图片共用同一实现，守卫拒绝事务时返回明确失败。
- GIF、浮动图片、裁剪、替换、图片格式上下文、页眉页脚及表格内图片仍未覆盖。

## XLSX：快速填充

- 对照固定源 `ribbon-actions.ts:2082`，直接复用现有引擎 `inferFlashFillTemplate` / `applyFlashFillTemplate`。来源为目标左侧最多六列；单格选区按左邻列向下探测最多 1000 行，遇空停止。
- 选择单列目标，校验全部非公式普通示例，按字段拼接和固定文字推断，绝不猜测截取/大小写转换。与固定源差异：所有示例均需一致（源最多三个）；显式选区也限制最多 1000 行；含合并单元格时拒绝。
- 只填写空白普通单元格；已有值、公式（包括计算结果为空）、共享公式和富文本均保留。通过一次稀疏官方 `sheet.command.set-range-values` 命令写入，显式字符串类型保留以 `=` 开头的结果。样式和批注保持原样。
- 写入前复用保存差分预算预检及工作表保护检查；撤销/重做和草稿刷新恢复走既有历史/差分路径。
- 文本分列、删除重复值、数据验证、合并计算和其他数据工具仍是独立缺口。

## 执行证据与边界

- 定向前端回归：`docx-clipboard.test.ts`、`docx-insert-table.test.tsx`、`workbook-main-fill-goto.test.ts`、`workbook-ribbon.test.ts`，累计 70 项通过（Word 修复后 44 项、XLSX 两套 26 项）。覆盖真实固定 Tiptap 扩展/保存守卫、真实 Univer 公式与命令栈、撤销/重做、草稿恢复、公式/格式/批注保留、合并/保护拒绝及迟到图片写入取消。
- 独立代码审查发现并修复了图片读取期间选区/只读状态往返仍插入的问题：读取期间持续观察 transaction/update/destroy，保留取消标记，finally 移除监听；新增两个先失败后通过的往返回归。修复已获只读复核，Word 浏览器插图验收重跑通过。
- Python `test_docx_insert_paragraph_image.py`：12 项通过，沿用既有图片载荷/身份/资源写回回归。
- `tsc --noEmit`、Vite 构建、资源预算与 `git diff --check` 通过。测试输出仍有既有 Univer `getSnapshot` 弃用提示和两个选区构造警告。
- `DOCX_INSERT_CASE=picture node smoke/docx-insert-gui-smoke.mjs`：Chromium 140.0.7339.16，真实文件选择器插入 PNG，刷新恢复草稿，经真实 Python `patch_docx` 保存，下载后 python-docx 独立读取一张 9525×9525 EMU 图片，重开新修订显示图片，浏览器错误为空。产物目录：`/tmp/docx-insert-gui-3Uz46T`。
- `WORKBOOK_RIBBON_CASE=flash node smoke/workbook-ribbon-gui-smoke.mjs`：同版本 Chromium，真实画布选择 C1 并执行数据页签快速填充，刷新草稿后经真实 Python `patch_office` 保存；下载后 openpyxl 独立确认 C2=`Grace Hopper`，粗体和目标批注保留，C1 示例与范围外公式仍在，浏览器错误为空。
- 两个浏览器脚本使用替身 context/file/preview/save 响应模拟修订登记和下载路由；文件补丁及下载字节解析真实执行。尚不代表已验收部署环境 HTTP/数据库、生产授权或 Microsoft Office 桌面。功能开关未改变，未提交、推送或部署。发布/签发链未改动。
