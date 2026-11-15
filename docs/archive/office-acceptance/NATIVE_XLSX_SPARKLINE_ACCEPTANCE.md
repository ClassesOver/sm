# XLSX 迷你图新增专项验收

日期：2026-11-10。**限定范围的三类型新增闭环专项已通过**：真实UI创建、Undo/Redo、草稿恢复、保存下载、独立ZIP+lxml回读、明确新修订重开、真实跨表来源绘制，以及实际宿主格几何和截图检查。初次发现的柱形/盈亏越格由engine agent修复后，root统一构建，使用既有三产物resume完成复验，新增保存次数为0。更广范围仍见末尾边界，不能据此宣称完整迷你图编辑能力。

## 已执行与证据

root统一构建/预算（root放行证据，不冒充本agent运行）：`/tmp/workbook-sparklines-data-split-{build,budget,contract}.log` 全exit0，tsc+Vite40.50s。之后本agent在冻结dist启动4273 smoke；未build、未修改生产代码。

- 脚本：`frontend/smoke/workbook-sparklines-built-smoke.mjs`，说明同名`.md`。
- 初次运行日志：`/tmp/workbook-sparklines-built.log`，exit0，Chromium140.0.7339.16。
- checkpoint：`/tmp/sparkline-built-AbVJe8/`，`saveCount=3`，实际加载124个JS均HTTP200且字节SHA匹配static，`errors=[]`。
- 独立回读：各`*-result.json`的independent来自独立Python zipfile+lxml（非engine回读），ZIP CRC、XML/rels可解析、单一根extLst、无根外ext、两组（已有+新增）、类型/宿主/绝对引用均匹配。

| 类型 | 源→新修订 | 下载SHA256 |
| --- | --- | --- |
| line | 1→2 | `1d41ee718cd8b4e0cbbc1effc7b079a179d46407af7dc10896d7829d2b1c6aa1` |
| column | 10→11 | `59c52e2ea5d1534fbe4dba1d78e472763c4d709329685783c1dbf4d415e6ec0a` |
| stacked | 20→21 | `cac7df8240f3d75e6ddf0150837392c534ebed5f5462060a0e5ecbe576afc028` |

三来源均通过真实Ribbon创建（主表`迷你图 O'Brien`，B4:D5→E4/E5）→Undo/Redo→草稿reload→实际native_office.patch_office→浏览器下载SHA→ZIP/lxml→显式新修订重开→store检查。保存操作仅`appendSheetSparklines`，每源1组2宿主；完整公式例如`'迷你图 O''Brien'!$B$4:$D$4`。

原有G2跨表线引用`'来源 ''中文'!$B$2:$D$2`，sourceSheet在真实store精确保留；原组series/negative色、unknown attrs、raw XML不变；foreign ext raw不变；所有非目标parts SHA不变。外表真实值[-2,8,1]与宿主表[1,-2,3]不同，实际G2 stroke路径为(530,46)→(600.5,26)→(671,40)，满足外表几何，排除把外表来源画成宿主表。

## 初次发现的绘制缺陷（已修复并复验）

目视已检查line/column/stacked-reopened.png。line正确处于E4/E5；column与stacked越格：

- 同一实际画布中E4格内y=74..94，E5格内y=98..118（20px内部高度，格高24px）。
- column E4三柱fillRect分别y62/h12、y73/h1、y54/h20，上溢到前一行；E5同样错位。
- stacked E4正柱y64/h20、负柱y84/h20；基线在格中但柱高取整格内部高度，导致上下越格。E5重复相同问题。

原脚本只验证发生绘制及跨表路径，没有验证bar geometry containment，故机器ok范围有限。本轮补充断言后必须再次用已保存文件重开绘制；不得为得到“绿色”删去越格断言。修复由engine agent负责，root统一构建/预算后放行resume。下节记录最终复验；只关闭本次三类型新增范围，不关闭原生组编辑等完整范围。

## 边界

已有三保存无需复做。HTTP授权/修订注册是测试替身，不是生产鉴权验收；未执行桌面Excel/打印等价验收。改名/删页、201行/重复宿主/最右列、结构保护、readonly/保存锁及数值编辑即时刷新尚未在此built专项跑过；应依各自定向测试/后续风险验收记录，不推定完成。已补充 bridge 层按宿主删除协议 `removeSheetSparklines`：严格校验目标、局部删除 x14 节点并保留其它组与 foreign extension；定向测试覆盖部分删除、删除最后宿主及非法目标。前端 journal 使用官方 mutation/history 支持删除并生成保存操作。

### 2026-11-11 原生迷你图组参数编辑闭环

新增 `editSheetSparklineGroup` bridge 操作，以宿主定位其 x14 组，局部更新类型、系列色、负值色、标记和坐标轴属性；通过读回校验更新值，并保留同表其它组。前端 controller 暴露 `edit()`，使用官方 mutation/history 写入 Undo/Redo journal，保存时输出编辑操作。定向验证：workbook engine `bridge/sparkline-additions.test.ts` 32项通过；前端 `workbook-sparklines.test.ts` 24项通过；workbook engine typecheck通过。当前未新增 Ribbon 参数编辑对话框/built验收；跨表新增仍为缺口。


## 最终冻结构建与无重复保存复验

root放行的最终构建/预算/contract日志为`/tmp/workbook-sparklines-bars-{build,budget,contract}.log`，全exit0，Vite40.21s（root执行）；本agent随后执行：

```sh
SPARKLINE_RESUME_DIRECTORY=/tmp/sparkline-built-AbVJe8 node smoke/workbook-sparklines-built-smoke.mjs > /tmp/workbook-sparklines-bars-built.log 2>&1
```

结果exit0：三case均`resumed=true`、**saveCount=0**、124实际加载JS身份均200且匹配磁盘SHA、errors=[]。最初3次保存与本次重开的三下载SHA完全相同。续跑又独立ZIP+lxml回读并重新HTTP下载，未用已存在结果文件跳过真实浏览器重开。checkpoint的各`*-result.json`及`summary.json`现在记录最终构建结果；首次机器summary仍完整保留在`/tmp/workbook-sparklines-built.log`；旧截图与旧逐项result未在覆盖前备份，现已被最终内容替换，不能声称旧文件另存或把最终截图当首次截图。初次实际canvasCalls由当时工具读出，原值记录于上节缺陷调查及协作消息；初次summary不含完整canvasCalls。`final-bars-evidence/`只是最终column/stacked截图与结果副本。

严格几何断言从renderer `targetBounds`读取实际skeleton坐标，而非截图估算：E4外格`x352..440/y72..96`、E5外格`x352..440/y96..120`；内边距2px后有效y分别74..94及98..118。新line所有点在实际格内；column和stacked每个fillRect均完整在一个实际目标格内，每格至少三个柱。stacked另按实际中线84/108检查第1/3正柱在上侧，第2负柱在下侧。

最终column E4三柱`y82/h4、y86/h8、y74/h12`，E5对应`y106/h4、y110/h8、y98/h12`；既保留正负值相对于零基线的方向，又无越格。stacked E4正柱`y74/h10`、负柱`y84/h10`，E5正柱`y98/h10`、负柱`y108/h10`。各case真实canvasCalls及targetBounds保存在对应result；跨表原生G2折线仍符合外表[-2,8,1]的路径。

最终截图`/tmp/sparkline-built-AbVJe8/{line,column,stacked}-reopened.png`已目视检查：E4/E5三类型清楚可见，column/stacked均无相邻行溢出，G2外表线保持。截图不代表桌面Excel视觉等价。

最终身份清单：`/tmp/workbook-sparklines-built-manifest.json`，含124实际JS、当前bridge/原生许可/探针、原fixture、三实际保存/下载文件、最终JSON/截图、前后日志的SHA与大小；`ok=true`、`errors=[]`。该清单只代表实际加载和列出的文件身份，不推定未加载功能已验收。

集成源码与定向测试证据由root独立维护于[NATIVE_XLSX_SPARKLINE_INTEGRATION_VERIFICATION.md](NATIVE_XLSX_SPARKLINE_INTEGRATION_VERIFICATION.md)，与本文真实built证据分开。最终manifest的phases分别登记初次三保存与最终冻结dist的零保存重开，保留两阶段各自实际加载资产身份。
