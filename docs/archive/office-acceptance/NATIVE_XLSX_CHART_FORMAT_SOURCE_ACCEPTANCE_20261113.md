# XLSX ChartFormatPane 源控件实现与验收边界

固定源为 genoffice-source-full commit f8c17004fb730df11f0f743164ffd8b4281bb38c，ChartPanels.tsx:148–364；本次不重做已交付选择性粘贴/SelectData。

## 产品实现

- 新增完整格式侧栏，使用原授权 chartPath/sheet/workbook/source 目标，经现有 applyChartEdits、NativeDraft、撤销恢复和保存链写回；没有增加平行 writer。
- 接入系列/点颜色、单点分离、标题、图例、标签类型/位置/格式、网格线、轴界限自动值、分类间距、整体分离、圆环孔径；沿原 XML 文档位置识别系列，点保持原索引。
- reader 补间距/孔径/分离及 line/area 轴和标签；预览直接使用读回格式，圆环使用真实内弧、分离标签同步移动，补颜色/网格线/line 标签。
- 最终真实浏览器发现 window capture 的拖动处理器消费 pointerdown，使 root 元素选择收不到事件。最小修复由已校验坐标委托原元素命中/系列到点窄选；resize 不委托，继续原权限/拖动提交链。

## 冻结与证据

证据根目录：/home/junge/codex-evidence/smart_reporting/office-component-inventory-20261113/xlsx。

- final-source-v2 manifest：6d89e82804f0535f999491b487ab192608a6fe1b5cb75674bf71c299c8eb438e；格式读写闭环为 browser-final-v2-r2，283 实际 HTTP 资源逐 SHA 比对、浏览器/console 错误空。保存文件 SHA 6706d25c39d39aadabfeb5c7a3b1599d463c5e725af8e0fd8f4a7c1501bdb62e。
- 独立 openpyxl/lxml 验证 column 间距300、轴最小值自动/最大30、网格线/标签位置格式/系列点颜色、pie/doughnut 分离30/55及孔径60、line 数字格式；仅 chart1–4 XML 改变，源单元格、其它工作表与无关部件不变，草稿恢复/UndoRedo/保存/下载/新修订复开通过。
- final-source-v3 仅加捕获修复，manifest：6f88215fdd66b5ec194b0ed03e9b445d3dae667041e1055722f907b357526ffb；统一 tsc、Vite、原预算通过（由 root 记录），未调预算。最终 static manifest：fffa484afba22adf36d470529e5305ad858a19a7f3ce91b43e0503373fa61c52。
- v3 仅跑受影响 point-browser-final-v3-r1：独立截图像素确定实际 line 第三 marker，真实 mouse 首击 series:0、再击 point:0:2；真实调色板单点改蓝后仅一条图表操作，一次保存下载，独立 lxml 验证只改 chart4.xml、dPt idx=2/color=0070C0，新修订复开回显通过。284 HTTP 资源 SHA 一致，浏览器/console 错误空。文件 SHA 8e25f63590a52ac75e7ad0a829b0c79c505ab8a1aaf4e21dcf6c744831e7043f。
- xlsx-runtime-final-v2/dist/cli.mjs SHA：dc60bac91cc61fc9da391a179478cef05307758d00fc1bdf79f27df423fe2bbb。显式包解析排除 workspace symlink 源混入，86 业务输入逐项匹配 v2 且与 v3 相同，169 依赖输入另列身份，实际 fixture CLI inspect 通过；记录位于 xlsx-runtime-final-v2/input-identities.json 与 v3-input-compatibility.json。
- reader 5、预览与 pane 102、host 3、选择/交互27、真实双捕获集成1定向通过；保留 RED 与 r1/r3/r4/r5/r6 失败诊断，不重复完整套件。

## 未扩大声明

renderer 363 文件/147 PascalCase 函数是盘点宇宙，不是已完成功能；逐控件映射在 chart-format-control-mapping.md。已接线不等于全部枚举手工验收，未实际执行的 title/legend/label 枚举、scatter/radar 轴边界仍保留 partial/unknown，不将名字或 grep 命中记为完成。

v3 与当前 workspace 有外部并发 print headerFooterPictures 差异；本轮只在 v2 上应用三文件最小捕获补丁，未纳入该打印改动，也不宣称当前 live 工作区整体经过验证。正式 runner 在产品冻结之外单独记录文件 SHA。

两次真实保存 validation.ok 均为 false，原因 native_source_review_pending，下载照常签发；没有标记业务事实或完整版式验收通过。未修改发布非阻断契约、Plotly、共享构建配置或共享 static/dist。

## 失败记录与最小修复

- browser-final-v2-r1：line位于viewport底部，实际点未显示，探针无可见点；截图确认。
- browser-final-v2-r2：移除未证明点选探针，仅记录格式/文件闭环通过，不宣称Canvas点选。
- browser-final-v2-r3：滚至底锚后line可见，但离屏cache Canvas transform推导点坐标落到L53格，真实点击进入单元格；截图独立证明探针坐标不成立。
- browser-final-v2-r4：共享Playwright browser cache被外部安装过程更改，启动前缺chromium_headless_shell-1187；保留失败，之后显式固定snap Chromium。
- browser-final-v2-r5：截图RGB探针错误假定默认主题68/114/196；PIL实测实际line marker为Office源主题79/129/189，位于可见line第三点。
- browser-final-v2-r6：独立截图确定marker(1182,788)，elementsFromPoint首项CANVAS，真实两击未缩point；确认产品缺口，未归咎runner。
- 最小产品修复：workbook-chart-selection.ts新增selectElementAt复用原hit/narrow，workbook-chart-object-interaction.ts在非resize捕获手势中经授权后委托，workbook-main.ts只新增该callback。RED证明window消费后原root指针不收到、委托0次；GREEN同装两处理器后真实pointerdown/up/click两次series→point原idx2、blank清空后重新series、resize/protected不委托、无历史。

三文件精确patch与before/after SHA位于chart-format-capture-fix.patch、chart-format-capture-fix-inputs.json，main v3预期SHA af6926062116d323e655e7a043c871302c497e20de3effad697f04905cef6b68。外部print修改明确排除。

最终v3并未重跑v2全部控件链，仅运行point-only受影响流程及一次单点保存必要校验；v2r2+v3point证据边界分别成立。
