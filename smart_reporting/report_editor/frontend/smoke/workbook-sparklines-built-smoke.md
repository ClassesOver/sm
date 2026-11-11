# XLSX 迷你图 built smoke

脚本：`workbook-sparklines-built-smoke.mjs`。最初准备阶段只做静态语法检查；后续已在root统一构建/预算放行后完成三真实保存，并在renderer修复后用同三产物零保存resume复验。完整结果见专项ACCEPTANCE，不能重复初次保存。默认独占 Vite preview 端口 **4273**。

```sh
cd smart_reporting/report_editor/frontend
node smoke/workbook-sparklines-built-smoke.mjs
# 故障后，使用日志给出的 checkpoint 目录继续：
SPARKLINE_RESUME_DIRECTORY=/tmp/sparkline-built-XXXXXX node smoke/workbook-sparklines-built-smoke.mjs
```

`SPARKLINE_SMOKE_PORT` 可覆盖端口。默认输出 `/tmp/sparkline-built-*`，`SPARKLINE_RESUME_DIRECTORY` 指定持久checkpoint目录（脚本会创建）。源fixture首次生成即持久化，续跑复用完全相同字节，不因ZIP时间或core创建时间变化导致假失败。

当前最关键范围：3个独立源修订（1/10/20），每个经真实UI新增line/column/stacked一种，选择 `B4:D5`，每行3列源、右一列 `E4/E5` 为宿主；三源共3次成功保存。主表 `迷你图 O'Brien`，跨表来源 `来源 '中文`，断言保存引用单引号双写且绝对地址正确。

每源执行：Ribbon创建→读取真实store→Undo/Redo→检查草稿变化→刷新恢复→真实保存→下载SHA→独立Python ZIP CRC/lxml XML回读→明确打开新修订→store和真实Canvas2D绘制→再次HTTP下载核验。保存回调经真实 `native_office.patch_office`，不伪造保存后的字节；HTTP授权/修订注册为测试替身，不代表生产鉴权验收。所有实际加载built JS返回200且与static磁盘SHA相同，pageerror/console error必须为空。

源文件已有原生raw组：宿主G2、跨表B2:D2、series `FFA1B2C3`、negative `FF445566`、unknown attrs `data-unknown=preserve-me/customFlag=77`；同一extLst另有foreign扩展，另有opaque customXml part。新增后严格比较已有group原始XML、foreign原始XML和所有非目标parts SHA。独立namespace-aware lxml要求单一根extLst、无根外ext、恰好2组，新增类型/两个宿主/完整原始公式均匹配。不用openpyxl重新保存输出。

画布证据不止store：只读 `window.__sheetsWebSparklines` store/draws/lastSkip，并观察原生CanvasRenderingContext2D的真实stroke/fillRect（包装仅记录后委托原方法，不注入运行时、不修改工作簿、不替换渲染器）。跨表原生线使用外表 `[-2,8,1]`，宿主表同范围为 `[1,-2,3]`，断言实际折线路径第2点最高，第3点位于第1和第2点之间，排除误读宿主表。新line要求默认色stroke，column/stacked要求默认色fillRect。store要求已有跨表 `sourceSheet` 精确，任何lastSkip视为失败；不会为当前跨表reader缺陷放松断言。canvas截图保存为各类型reopened.png，仍需root目视；不声称桌面Excel/打印等价。

断点规则：每次真实patch成功后先写 `revision-N.xlsx`，再写 `saved-source-R.json`，然后才返回save成功响应。后续下载、独立回读或重开失败，续跑识别saved checkpoint，校验SHA、重新回读并重开/下载，**不再点击已成功源的保存**。有saved记录但文件缺失/身份不符时失败，不回退重新保存。完整结果写 `line/column/stacked-result.json` 和 `summary.json`；保存成功与所有验收通过分别留证，不混淆。

本轮暂不覆盖：新增后改名/删页、结构保护、201行/最右列/单列/重复宿主错误、原生组编辑删除、跨表新增、非默认新增颜色、普通数值编辑后的即时刷新、readonly与保存锁。主要三源链先真实通过后再按具体剩余风险补定向向量，禁止重复已成功保存。现有raw跨表来源显示、unknown保真均已列入严格核心断言，不属于可忽略边界。

2026-11-10 初次真实运行发现柱形/盈亏越格，机器只检查绘制调用存在不足以判定视觉通过。已增强为读取renderer实际skeleton返回的targetBounds，每个bar完整处于对应宿主格2px内边距内；盈亏三柱另按实际基线校验正/负方向。折线全部点也必须在实际宿主格内。已成功保存checkpoint为`/tmp/sparkline-built-AbVJe8`，后续只能使用该目录resume，不得重复初次三保存。详见`../../NATIVE_XLSX_SPARKLINE_ACCEPTANCE.md`的进行中状态。

最终复验已通过，日志`/tmp/workbook-sparklines-bars-built.log`：saveCount=0、3个resumed=true、124实际JS身份匹配、errors=[]。manifest `/tmp/workbook-sparklines-built-manifest.json`分段保留初次三保存与最终新dist重开，勿为重复检查再运行成功保存。
