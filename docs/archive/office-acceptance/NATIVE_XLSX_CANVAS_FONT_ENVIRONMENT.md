# XLSX Canvas 文字可见性：环境根因与预检

日期：2026-11-12。承接 [画布验收](NATIVE_XLSX_BAR_CANVAS_ACCEPTANCE.md) 中标题及网格文字缺失的观察；本次关闭该固定夹具在验收环境中的文字可见性问题，不认定任意字体/复杂版式完整对齐。

## 原始证据与因果隔离

在**空白页面**直接调用原生 Canvas API，无编辑器/字体注入：`20px sans-serif` 的 HELLO 宽度和非透明像素均为0；Arial、serif、monospace、system-ui、Calibri也为0。明确指定系统 DejaVu Sans 则有正宽度和实际墨迹。因此不能据旧截图推断为产品文字被隐藏。

真实页面的 fillText 诊断同样看到 `bar 1 / column 2 / bar 3` 与 `Category / First / Second` 的调用，颜色正常、globalAlpha=1，但 measureText.width=0。证据 `/tmp/workbook-text-diagnose-20261112/text-probe.json`。环境原始 `/etc/fonts/conf.d/52-orbit-os.conf` 以 strong alias 优先选择 `/usr/share/fonts/openai-sans/*.woff2`；已只读复制到同目录 runtime-fontconfig-original.xml。fc-match 与 Chromium 原生文字实验支持根因为该环境的系统 WOFF2 解析路径，而不是编辑器未发起绘制。

仅给浏览器测试进程指定 Fontconfig：加载原有系统配置、排除上述系统 WOFF2，保留已安装字体和其它回退。完全相同的源文件、路由与冻结生产资产，标题和网格文字恢复，诊断截图为 fontconfig-fixed.png。没有修改 /etc/fonts、生产渲染器、源文件字体元数据或部署配置；这是一项明确选择的验收运行环境适配。

## 防止再次误验收

- `frontend/smoke/canvas-font-preflight.mjs` 在加载app/web字体前，新建空白页，对7个字体族实际 measureText、fillText、getImageData；宽度有限且大于0，并且存在文字像素，才通过。字体族与配置路径/SHA进入证据，预检不自动改字体或静默重试。
- `canvas-fontconfig.conf` 是 Linux 进程级显式选择。正常环境可不指定；若默认字体画不出来，两个XLSX图表smoke会在 canvas-font-preflight 阶段直接失败，而不再把“条形存在/无JS错误”算作文字可见。
- 两个独立Pillow verifier从最终截图检查图表标题区域和源单元格表头区域的深色墨迹；不依赖DOM标签或仅有正文字宽度。这是存在性检查，不是OCR文字身份或逐字排版验证。

在仓库根目录复现（选择新的输出目录，脚本不覆盖既有结果）：

```bash
FONTCONFIG_FILE="$PWD/smart_reporting/report_editor/frontend/smoke/canvas-fontconfig.conf" \
PDF_SMOKE_STATIC_DIRECTORY=/tmp/workbook-chart-render-static-20261112 \
WORKBOOK_CHART_RENDER_DIRECTORY=/tmp/workbook-canvas-font-new-run \
node smart_reporting/report_editor/frontend/smoke/workbook-chart-render-smoke.mjs
```

保存链使用同一字体配置运行 workbook-ai-charts-smoke.mjs，并设置新的 WORKBOOK_AI_CHARTS_DIRECTORY。只对当前命令进程生效，未修改用户全局环境变量。

## 分层验收与身份

| 证据 | 结果 |
| --- | --- |
| 默认环境 RED | `/tmp/workbook-canvas-font-browser-20261112-red/canvas-font-preflight.json`：6个默认/别名字体均width=0、inkPixels=0，DejaVu正对照有1062像素；脚本在预检失败。 |
| 旧截图文字检查 RED | 新像素verifier检查旧green03截图，因三个标题墨迹均为0而失败；`/tmp/workbook-canvas-text-pixel-red.log`。旧条形几何结论保留，但不反推旧文字验收通过。 |
| 文字与条形 GREEN | `/tmp/workbook-canvas-font-browser-20261112-green/summary.json`：7族空白页预检通过；三个标题墨迹38/57/39像素，网格表头460像素；条形仍5/5/0、正负零线与分类间距通过。 |
| 保存、下载、重开 GREEN | `/tmp/workbook-ai-charts-browser-20261112-font06/summary.json`：真实HTTP/授权/Agno工具/Node writer/publication，修订4→5→6、UndoRedo、放弃删除与再采纳通过；独立OOXML数值/引用/另一图字节保全。修订5标题/表头墨迹71/295，修订6为40/295。provider为ScriptedModel、修订仓储为作用域内存夹具，不算真实provider或生产DB链。 |

Chromium140.0.7339.16；显式字体配置SHA=`da88df2f6b325fad1eb19cd179e214861d5b3356e539a0a3c52863c1b5662b21`。两个GREEN各169份实际JS/CSS与同一冻结构建核SHA，manifest仍为 `530d7dde396bfbbcc223084a782c7f27d94245bb8985ed6ff6b884856d54fa69`；运行错误数组为空。根任务再次独立核验全部资产与字体配置，查看实际恢复文字后的截图。

修订5下载SHA=`0d5537df8cb9f06d9bbe9986b405634f5a050235cc8ee2108afba1e00d295771`；修订6下载SHA=`26b316424aded3aba4e4beb781315cc2513f67eb4f858ae0ba30dff9aa6a46a1`。两次仍诚实返回业务/完整版式待复核，下载和重开不受阻。

本轮仅改smoke和验收记录，复用已完成tsc/Vite/预算验证的同一生产构建；JS语法、Python Ruff及diff检查通过，未重复构建或完整项目测试。仍不声明任意CJK/复杂脚本字体、精确Calibri度量、图例/轴/标签样式、跨表引用等全部通过；未合并部署，原两份PDF WIP stash保持原样。
