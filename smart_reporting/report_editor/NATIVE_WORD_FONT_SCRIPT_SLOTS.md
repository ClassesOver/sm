# Word 中西文字体槽选择

根因：live Ribbon、draft replay 和 bridge 将 fontFamily 无差别映射为 font。既有 eastAsiaFont 优先于旧 font 时，中文选择可能不改变实际中文字体；Latin 选择也不能明确只操作 ascii/hAnsi。

本轮提取固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的无依赖 `isEastAsianFontName`（源 font-list.ts SHA256 `fbf587949b074f719e12c8faf1a70fc4593afe7fdaa24522b1c8b159e68db6a1`）到共享 bridge/docx-font-slots.ts，保持 NFKC 和原正则语义。中文等东亚字体写 font/eastAsiaFont、保留 fontAscii；Latin 字体仅写 fontAscii，保留 font/eastAsiaFont。live/replay/bridge 共用；collector 转为原有单一 fontFamily 协议，不引入新的客户端字体槽写入权限。null 继续清所有字体槽与 themeRFonts。

generate 现有写入能力经真实 OOXML 测试已足够，本轮未修改。单一选区同时更改中西两槽、独立 complex-script/theme 槽改变保守拒绝；文字与脚本槽字体同时修改明确要求先保存再设置。默认空 mark 和全 null mark 规范为相同状态，不阻断纯文字修改。

验证：初始专项存在 CJK/Latin/replay/collector 失败，另有测试使用不存在 matcher，后者已修正而未算为生产根因。最终新专项 9 通过（`/tmp/docx-font-slots-defaultguard-green.log`）；受影响 Ribbon 18 通过、早期槽专项 6 通过（`/tmp/docx-font-slots-final-frontend.log`），原 format-range 5 通过（`/tmp/docx-font-slots-first-green.log`）。前端严格类型检查通过。新增 Python 直接执行 source TS bridge、不使用旧 dist：原有宋体 eastAsia + Calibri ascii/hAnsi + Arial cs，选微软雅黑/Noto Sans CJK SC/Times New Roman 的段落和范围 6 通过；null 全清 2 通过（`/tmp/docx-font-slots-native-source.log`、`/tmp/docx-font-slots-native-null-green.log`）。初次 null 两例失败仅因测试未防已完全移除的 rPr，已修正并只重跑两例。

本执行者未 bundle 或修改 main/home/assets；统一构建、实际浏览器字体显示及保存重开由 root 验收。

## 内置思源字体真实显示修正（2026-11-10）

真实构建暴露第二层问题：mark 已更新 eastAsiaFont，但 fixed-source resolver 因桌面 provider 不可用而将 Noto Sans CJK SC 按 Word 缺失字体规则替换 SimSun，`--doc-east-asian-font` 因而仍为衬线链。这不是陈旧 mark 元数据。新增真实来源 `runFaceDecls` 回归 `/tmp/docx-bundled-fonts-red.log` 先复现该 CSS 值。

最小 vendor seam 只登记 host 已实际加载的 browser faces，保留所有未命中字体的 undefined→system snapshot 原规则（避免全局 metrics provider 返回 null 意外屏蔽快照）。host 加载资产后登记原 woff2 提取指标，不冒充 DOCX embedded。metrics.json 记录逐资产 SHA，provenance.json 记录指标文件 SHA；vendor LOCAL 登记唯一算法适配文件与说明身份。

`/tmp/docx-bundled-fonts-green.log`：13 项通过（4 个 browser-face 测试与既有 9 个 slot 测试）。包括所选 Noto Sans 直接生成对应 EA CSS 头、保留 Latin slot，Arial/Caladea 及八个 snapshot-only face 前后解析结果完全相等，加载失败后清除旧登记，仅成功字体登记和真实 DOCX 嵌入字体优先。此处没有重建 bundle，最终真实构建/浏览器验收由 root 完成。


## 浏览器绘制与 Word 布局指标分离修正（2026-11-11）

11-10 的 browser metrics 登记不能作为 Word 原生 installed-face 证据：内置 Noto Serif
CJK SC 的 hhea 盒 1.437 被 EA 规则再乘 1.3 后变成布局因子 1.8681，造成同一复杂报告
正文四行从固定源的 113.015625px 增至 175.375px。新的 browserFontFace 仅授予已加载字体的
直接 CSS 绘制能力，保留真实 asset 盒指标；Word 字体替代、拉丁/中日韩布局因子回归固定源。
真实 DOCX 嵌入字体仍优先；fontChainMetricsPct 继续测量实际绘制盒。专项 8 项 RED→GREEN；
没有更改字号、1.3 常量、源 DOCX 或以页数为目标加入特判。原源应用实测证据见
/tmp/sr-word-complex-20261111/source-style-metrics.json；宿主 A/B 和最终公共构建由 root 记录。


后续只读 CDP 对照明确：固定源的混合正文通过拉丁范围别名命中 Caladea，中文命中
系统 Noto；浏览器内置 Noto 不应吞掉 ASCII 槽。故 cssFontFamily 的 browser 分支在
真实 CJK 链前保留源 latinSlotHead 前缀，assets/docx-caladea 仅增加固定源
KR Theme Latin GO 原始规则并复用现有 Caladea 二进制。新增混合/显式 ASCII/纯 EA
断言先红后绿，adapter 共 9 项通过。真实 glyph 盒测量与嵌入优先仍保留。源
Grid Strut 撤除前后该段高度相同，不以推测扩迁 PUA Blank 或其他 alias。
