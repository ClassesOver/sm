# XLSX 打印单元格边框增量验收

固定参照：`/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮覆盖现有活动工作表浏览器打印文档的显式四边边框，不代表完整 PrintDialog 或原生打印对齐。

## 源码与实现

- 固定源 `apps/sheets/src/renderer/print-html.ts:136`：NONE 不绘制，thin/default 0.75pt、medium 系列 1.5pt、thick 2.25pt。
- 固定源同文件 `:395`：共享边由上方/左侧单元格优先绘制；只有下方/右侧声明时保留该边；页边重新绘制。
- 固定源同文件 `:947`：使用 inset box-shadow，避免 CSS border 改变行列与分页几何；虚线和双线沿用源的实线打印表示；颜色按 `cssColor` 白名单回退。
- 本地 `frontend/src/workbook-print.ts` 复用已有 `LogicalStyle` 和 `fromUniverStyle`，保持原导出函数签名。边框尺寸随当前打印比例缩放。网格线使用相同的单边所有权逻辑，保持本地既有 0.5pt / #b7b7b7 颜色。
- 页内合并区域使用锚点样式，阴影绘制在整个 rowspan / colspan 单元格上。隐藏行列不参与相邻边判断。

## 定向验证

先运行 `npx vitest run src/workbook-print-borders.test.ts`，观察 5 项因缺少 boxShadow 而失败；实现后 5 项通过。独立 review 新增 RGB/RGBA 及水平、垂直合并区域相邻边用例，先观察 3 项失败，再修复到 8 项全部通过。

`npx vitest run src/workbook-print-borders.test.ts src/workbook-print.test.ts src/workbook-print-scale.test.ts src/workbook-print-routing.test.ts`：最初新增边框 5 项、已有打印 18 项、比例 2 项通过；旧 routing 2 项失败分别是动态导入 5 秒超时、mock 的 `runtime.univer.__getInjector` 缺失（`workbook-rtl.ts`）。本轮未修改 routing 和 RTL。

`npx tsc --noEmit`：发现其他任务中的 `docx-comment-thread.test.ts` 的 `done` 字段与 `docx-comment-thread.ts` 的 delete 非 optional 类型错误；打印文件未报类型错误。统一构建结果以 root 的最终验证为准。

## 浏览器验证脚本

在 root 统一构建后，从 `frontend` 执行：

```sh
node smoke/workbook-print-borders-built-smoke.mjs
```

脚本读取真实构建静态文件，经原生编辑器 URL 加载 openpyxl XLSX，用 File → Print 入口截获 iframe 的 `contentWindow.print()`。检查实际打印 HTML 的颜色、三阶线宽、双线实线表示、相邻边优先、合并与千分位格式。每个加载的 JS bundle 与本地静态文件做 SHA-256 对照；输出临时目录内 `source.xlsx`、`print.html`、编辑器截图、打印截图、`print.pdf` 和 `result.json`。这不会提交系统打印任务。

review 修复后的 `npx vitest run src/workbook-print-borders.test.ts src/workbook-print.test.ts src/workbook-print-scale.test.ts` 共 28 项通过。冻结构建后的实际浏览器验收通过（Chromium 140.0.7339.16）。证据目录 `/tmp/print-borders-built-BX3AnQ`：

- `source.xlsx`：真实 XLSX 输入。
- `print.html`：通过真实 native URL → File → Print 截获的 iframe 文档。
- `native-print-entry.png`：入口截图。
- `print-rendering.png`：打印媒体截图，已人工查看；四边线条、绿色合并区域和千分位内容可见。
- `print.pdf`：1 页 A4（594.96 × 841.92pt），实际生成并经 pdfinfo 确认。
- `result.json`：所有断言通过，浏览器 pageerror 为空，加载 bundle SHA-256 与冻结静态文件一致。

实际 HTML 显示 thin 0.75pt、medium 1.5pt、thick 2.25pt；绿色合并单元格为 rowspan=2 / colspan=2，右侧蓝色冲突边未被绘制，数值显示为 `1,234.57`。

默认沙箱首次运行被 `listen EPERM 127.0.0.1` 拒绝，按正常提权流程运行后到达真实入口。首次浏览器断言因 Chrome 与 jsdom 的 style.boxShadow 序列化不同而失败；只调整 smoke 读取原始 style 属性并增加阶段日志/请求超时后通过，未修改生产代码或构建产物。

## 边界

- 本轮不新增完整打印范围选择对话框、打印机/份数配置或工作簿多表打印。系统浏览器打印面板仍由浏览器管理。
- header/footer、图表/浮动对象、跨页合并内容重组与条件格式样式未在本轮验收。
- double/dashed/dotted 等按固定源转实线，未声称保持 OOXML 线型。
- 合并区域使用锚点边框；没有聚合覆盖单元格单独设置的边框。水平与垂直合并锚点的相邻边冲突已有回归覆盖；复杂合并区域不同长度边段仍未单独验收。
- NONE 在快照样式映射中不生成显式边线；打开打印网格线时仍可显示网格线，与源的 NONE 处理一致。

后续共享构建连续性核对：浏览器专项完成后，共享 static 又被其它工作重建。root 实读本专项下载 XLSX，并比对两份浏览器资源清单：各125/129资源字节未变；4份共享宿主资源发生变化，不能称当前整包重新通过同一专项。workbook-main、CSV独立chunk及print-settings实际字节未变，见 /tmp/xlsx-parallel-shared-build-continuity-20261111.json。浏览器结论绑定各自原冻结证据；未重复完整测试。
