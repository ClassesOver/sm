# Word / XLSX 中文字体

原文件来自 GenOffice 固定版本 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，`apps/docs/src/renderer/fonts/`。Noto Sans/Serif CJK SC，SIL OFL 1.1（LICENSE-OFL.txt），原二进制及 SC/GO 四条 @font-face 未修改，身份见 provenance.json。两个 woff2 共 4,912,432 字节；SC 和 unicode-range 限定的 GO 复用相同文件。

GB2312 子集含常用汉字及中文标点/全角字符（GB2312 汉字为 6763 个）；生僻字继续系统后备，粗体按源由浏览器合成。不是宋体/黑体/楷体/仿宋等专有字体的原字形，不承诺全部汉字覆盖。Word 和 XLSX 懒加载入口共享这两个资产；菜单已提供两项内置思源字体及五项常用系统字体选项（系统字体存在与否取决于运行环境）。

`metrics.json` 使用项目 `.venv/bin/python` 的 `fontTools.ttLib.TTFont` 从上述两个 woff2 的 `head.unitsPerEm`、`hhea`、`OS/2` 原始表提取，逐字体保留原文件 SHA256。Word 仅在 `document.fonts.load` 实际返回字体后向来源解析器登记对应指标，避免来源桌面字体缺失规则将内置思源黑体替换为宋体；不改变其他字体的静态快照或文档嵌入字体优先规则。


## 2026-11-10 中文字体扩展

额外内置霞鹜文楷（LXGW WenKai）、马善政毛笔楷书（Ma Shan Zheng）、站酷小薇（ZCOOL XiaoWei），均采用 SIL OFL 1.1；各自授权全文随文件保留。霞鹜文楷授权明确允许网页子集/WOFF2 保留名称，本项目仅作网页字体交付。三个文件来自固定上游提交，原文件 SHA256、转换后 SHA256、来源地址和授权文件见 provenance.json。这是本地扩展，不属于固定 GenOffice 源码已有功能。

新增字体使用 FontTools 保留原名称、字形与排版表，只取 GB2312 及 U+0020–00FF 子集并转换为 WOFF2。GB2312 含 6763 个常用汉字，各字体实际覆盖不同，不能视为全 Unicode 覆盖。粗体和斜体仍由浏览器合成。文件内不嵌入这批字体，桌面 Office 打开时仍需要安装对应字体；本轮未修改服务端 PDF 渲染字体配置。

Word 将三个英文 family 名识别为东亚字体，选择时写入 eastAsia 并保留原 ascii/hAnsi；渲染器仅登记实际加载成功字体的原始指标。XLSX 在创建 Canvas 引擎前加载三款字体，菜单展示中文名，保存使用原 family 名。
