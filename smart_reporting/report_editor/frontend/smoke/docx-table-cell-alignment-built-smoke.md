# Word 九宫格单元格对齐 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-cell-alignment-built-smoke.mjs
```

默认4242（`DOCX_CELL_ALIGNMENT_SMOKE_PORT`）；只使用root最终assets/bridge，不build。fixture源普通及横纵合并/隐藏continue，奇数twip网格、atLeast9000行高、多段中文emoji/富文本/空段、LTR/显式Hebrew RTL/推断RTL/样式继承RTL、Heading1样式段落、RTL编号list。真实样式Heading1在cell converter里仍docParagraph，人工PM docHeading过滤另由UI测试验证，二者不混称。

普通来源完整9组合逐修订save/HTTP下载/项目Python patch/ZIP回读/重开；复杂合并来源top-left/center-center/bottom-right逐修订，共12次保存。每步公开按钮active、精确DOM undo/redo/draft；computed text-align+direction换算真实视觉水平对齐，9组合按相同horizontal比较真实首段相对cell的top偏移，须top<center<bottom。

严格XML：owner直属段落jc按显式/继承RTL互换、inferred不互换，top清vAlign；merged continue只传播vAlign，隐藏段落jc原字节不动；非目标cell全文不变。仅屏蔽jc/vAlign后整个XML逐字保持，其他parts SHA/cell身份保持，奇数网格/行高/段落rsid/runs都不脱敏。真实download SHA+JS200/本地SHA匹配，console/pageerror为空。

准备状态：Node语法、嵌入Python compile通过；bridge capability尚待engine/root最终构建预检，不冒称built完成。UI5项GREEN及最终tsc exit0，未重复旧probe/完整测试。

最终迁移后实测 `/tmp/word-cell-alignment-migrated-built-smoke.log` exit0、ok=true/errors=[]，12次保存/真实HTTP下载/重开及实际九宫布局通过。产物 `/tmp/docx-cell-alignment-built-rHNpVF/`；前两次probe暴露的oracle与真实CSS继承缺陷分别修正并保留证据，见专项ACCEPTANCE。新doc_engine bridge实际运行，授权/修订为本地替身，不冒计生产HTTP/桌面Office/PDF。
