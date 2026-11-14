# 合并计算：PC 窗口与真实 XLSX 保存检查

在 frontend 目录执行，显式指定本次冻结构建、manifest SHA 和全新证据目录：

```bash
TMPDIR=/dev/shm \
CONSOLIDATE_SMOKE_STATIC=/dev/shm/本次构建 \
CONSOLIDATE_EXPECTED_MANIFEST_SHA256=本次已核对的manifest摘要 \
CONSOLIDATE_SMOKE_DIRECTORY=/dev/shm/全新证据目录 \
node smoke/workbook-consolidate-built-smoke.mjs
```

通过真实 Ribbon、定位窗口、合并计算窗口和 Ctrl+C 检查五种按位置函数及三种左列标签函数；每步核对旧值、结果、撤销和恢复。刷新后再次读取全部结果，然后只保存一次、下载、重开新修订并再次精确复制。18 个来源引用及空引用错误的取消操作不得产生草稿。

`office-xlsx-analysis-layout.mjs` 检查五种视口的窗口边界、固定标题/底部、滚动阅读区、控件大小、焦点环、Tab 循环、五点命中及输入/草稿不变。截图需人工复核。组件回调夹具与这个真实工作簿宿主是两种不同证据，不累计为功能数量。

`office-xlsx-consolidate-fixture.py` 通过真实 Python `patch_office` 保存；用独立 ZIP/XML/openpyxl 核对 33 个目标单元格的准确公式或标签、目标样式、来源工作表字节及范围外 XML。非空缓存必须准确；缺失公式缓存要求 `fullCalcOnLoad` 且不能是手动计算模式，再由浏览器逐项验证新修订的实际重算结果。不会把无缓存文件误称为已有完整缓存，也不静默灌入预期值来制造通过。

保存应答明确返回 `validation.ok=false` 和结构化告警。页面必须展示具体原因，同时仍能下载与重开文件。HTTP 身份、授权、CSRF、修订登记和保存应答是夹具；此检查不代替真实服务端数据库、授权、完整发布门禁或桌面 Excel 实机验收。

已有 `saved.json` 或 `revision-2.xlsx` 的目录禁止普通重跑。保存后失败时保留原文件与回执；使用相同路径并增加 `CONSOLIDATE_SMOKE_REVIEW_ONLY=1` 只读检查，保存路由在此模式强制拒绝写入。`summary.json` 和 `layout.json` 描述最后一次运行；初次保存前的八模式证据单独保存在 `modes.json`，初次日志和失败截图应另外保留，不能将只读检查的 `saveCount=0` 解读为从未保存。

本批隔离构建仅修改输出和缓存位置；原生 PDF 运行时复制插件改为从既有 static 复制相同资源，其他源码变换与分包配置沿用 `vite.config.ts`。没有覆盖项目 static；运行验收必须引用隔离目录和对应 manifest，不能冒称已经部署。
