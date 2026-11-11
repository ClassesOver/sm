# 定义名称：工作表删除依赖原子性调查

本轮只新增隔离 engine 测试、真实浏览器探针和本文档；不改生产、manifest、dist/static。fixture 没有 CF、DV 或普通单元格公式，只有定义名称 `DeleteDependency`。

## 固定来源与引擎范围

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `xlsx-sheets.ts::definedNamesReferenceSheet` 明确跳过 localSheetId 属于被删表的名称，因为它随表一起丢弃；全局和其他存续表局部名称引用被删表时仍应拒绝。源文件 SHA-256 `f1b20c4fd4868b39f4fe0e0c2c3d5a462343d87c84d9f091037f778249467679`。本地 `sheet-ops.ts` 在 ZIP 修改前调用该检查。

独立 `packages/xlsx-engine/tests/defined-name-sheet-removal-investigation.test.ts` 验证 7 个边界：

- 全局 Source 引用拒绝。
- Other 局部名称的 quoted lowercase Source 引用拒绝。
- Source 自身局部名称引用 Source，允许删除并从文件中丢弃该名称。
- Other 引用、字符串常量和 quoted/unquoted 外部簿引用允许，存续表与 styles.xml 字节保持。

首次 6 通过、1 因测试将空可选 definedNames 属性误写成必为 [] 失败（`/tmp/defined-name-sheet-removal-engine-investigation.log`）；修正测试为 `model.definedNames ?? []` 后只重跑受影响的 Source 局部对照，1 通过、6 未选（`/tmp/defined-name-sheet-removal-engine-local-control.log`）。没有引擎生产 RED，未重复完整旧套件。

## 真实浏览器 RED：全局与存续表局部

`frontend/smoke/workbook-defined-name-sheet-removal-gap-probe.mjs` 使用 openpyxl DefinedName 创建 ZIP，Vite 4229，通过官方删除命令操作。探针比较完整 workbook snapshot、定义名称、工作表列表、undo/redo 和 localStorage 草稿，而不只相信返回值。

全局（`/tmp/defined-name-sheet-removal-browser-global.log`）和 Other 局部（`/tmp/defined-name-sheet-removal-browser-local.log`）结果一致：

- 删除返回 true，Source 实际消失，名称引用从 `Source!$A$1` 变为 `#REF!`。
- undo 与 redo 均 true，但 undo 后完整 snapshot 与原始 snapshot 不相等；redo 可重复删除后的 snapshot。该事实不等同于已经定位哪一字段丢失，下一阶段需细分差异，不能泛称所有内容不可恢复。
- 本地草稿仍为空，反馈 `本地草稿暂未更新：仍有定义名称引用 "Source"，已拒绝删除。`。
- pageErrors 为空，删除原子性、完整 snapshot、无新历史三条断言真实失败。

额外 Source 自身局部 exploratory run（`/tmp/defined-name-sheet-removal-browser-owned-scope.log`）实际允许删除并产生 applySheetEdits 草稿，符合来源语义；其运行时 facade 仍暴露带已删 scope 的名称元数据，但现有 `liveDefinedNames` 会过滤已不存在 scope。该次运行仍用旧拒绝断言退出失败，不能误算为生产缺口或允许对照 GREEN。当前探针已按 `NAME_REMOVAL_SCOPE=Source` 区分允许语义；本轮未再次运行该对照。

## 最小下一方案

1. 删除前读取当前定义名称（含全局与本地身份），对存续 scope 的 refersTo 复用现有引用检测和 runtime 同簿限定符规范化；删除自身 scope 的名称直接排除。保护字符串、外簿、大小写，保留 `_xlnm` 来源边界，不依赖过滤后的名称管理 UI 列表假设完整。
2. 用户已修改/移除引用时，先将当前名称差分按最终 sheetName/scope 写入实际文件，再执行来源删除验证。与 CF、DV、cell edit 前置写回共同避免“live 已解除、旧文件仍阻断”。
3. 不完整名称 XML、隐藏/内置名称须依据 actual source 保守判断；缓存绑定模型与结构签名，禁止使用客户端 raw 字段授权。
4. 验证原子拒绝时 snapshot/history/draft 均原状，清除依赖后实际保存成功，rename/reorder 后 scope 不串表，并定位 undo 完整快照差异。图表依赖未在本轮验证，不宣称被覆盖。

当前仅记录待修复的前端原子性 RED，无生产实现改动。

## 原生 Python 参数验收与 scope API

新增 `reporting/tests/test_workbook_defined_name_sheet_removal.py` 使用真实 openpyxl DefinedName ZIP，`patch_office` 调用现有 engine，**19 通过**（`/tmp/defined-name-sheet-removal-native-python.log`）：全局/Other 局部 × 三种本地引用共 6 拒绝；Source 自身局部随表丢弃 1 允许；两种存续 scope × Other/literal/两种 external 共 8 允许；两种 scope × 移除或改为安全引用后删除共 4 成功。另设同名但不同 scope 的安全名称，确认写入/移除不串 scope；存续值、字体、填充及 worksheet/styles 原字节保留。仅运行新增文件。

可复用 API：`liveDefinedNames` 返回 `{name,refersTo,scopeSheetId?}`；`definedNamesPlanOperation` 结合实际 sheet ID→name 映射产生 `applyDefinedNames`，sets 为 `{name,refersTo,scopeSheetName?}`，removes 为全局 string 或局部 `{name,scopeSheetName}`。文件写入根据当前标签顺序解析 localSheetId，删除表后作用域重编号由 sheet plan 负责。

来源未投影边界：`parseDefinedNames` 跳过 `_xlnm.` 与无效 localSheetId；`liveDefinedNames` 同样过滤内置名称和已不存在 scope，因此完整删除预检不能只依赖管理 UI 返回列表。文件删除检测直接扫描 actual workbook.xml，包括这些原始名称；前端保守保护应基于可信真实 workbook.xml 并绑定当前模型/结构签名，不可接受客户端 raw 字段授权。内置名称更新仍使用既有页面设置路径，不应顺带扩展名称编辑器权限。

## 前端修复：全局、局部及可信来源

新增`assertDefinedNameSheetRemoval(workbook,subUnitId?,source?)`，直接遍历完整`getDefinedNames()`而非会过滤内置名称的管理器列表。在基础删除与任何官方followers之前，对global和存续表local检查当前引用；被删表自有local排除。复用共享公式引用检测及exact runtime unitId归一，保护sheet大小写、字符串和其他外部簿。

source只接受root绑定实际ZIP的`workbookXml`及加载时记录的`unprojectedNames`稳定scope ID。原XML localSheetId先解析原sheetName，再匹配live sheetId；只保护初始导入失败名称、内置`_xlnm`及无法核对的scope/来源，不能把当前缺席当成导入失败，也不扫描完整旧user name导致用户解除引用后误拒。未知前缀或无法读取scope明确拒绝；本轮未新增共享名称公式解释器。内置打印名称保守使用实际来源，并不宣称所有内置名称编辑都已完整投影。

helper缺失RED `/tmp/workbook-defined-name-removal-helper-red.log`后10项GREEN `/tmp/workbook-defined-name-removal-helper-green.log`，初始失败key与完整旧name区别的新增控制GREEN `/tmp/workbook-defined-name-removal-projection-green.log`。collector-before-original新case RED `/tmp/workbook-defined-name-removal-collector-red.log`后，与CF/DV/cell三个原子删除case合计4项GREEN `/tmp/workbook-defined-name-removal-collector-green.log`。原有测试桩显式提供空名称facade，未把缺失facade默认为空。

真实开发态全局与Other局部拒绝分别`/tmp/workbook-defined-name-removal-dev-global-green.log`、`/tmp/workbook-defined-name-removal-dev-local-green.log`：deleted=false，完整snapshot深比较相同，名称/scope/引用保持，undo/redo=false，localStorage不变，pageErrors=[]。全局解除引用闭环`/tmp/workbook-defined-name-removal-dev-clear-green.log`：先拒绝，再官方facade setRef Other!$B$1，删除/undo/redo、草稿重载、真实Python patch_office/openpyxl保存及修订2重开通过；操作严格先applyDefinedNames，再applySheetEdits，存续worksheet/styles字节保持，值B1:B5=[1,2,3,4,5]。

## 自有局部名称必须随表参与同一历史事务

三表Source/Other/Third真实探针先删Source ownlocal，等待结构同步后再删Other，发现facade残留scope=sheet-0、ref=#REF!，导致第二次删除被新的scope完整性预检拒绝；真实RED `/tmp/workbook-defined-name-removal-owned-second-red.log`。这不能通过泛跳未知scope解决。

`workbook-defined-name-scope.ts`改为在官方SheetInterceptorService收集完成后，仅按实际unitId与owned名称ID替换该组官方Set/Remove followers，使用RemoveDefinedNameMutation redo与完整原始SetDefinedNameMutation undo。整组仍在基础删除前收集完成；其他同名scope条目不改。真实Univer新case先RED `/tmp/workbook-defined-name-owned-history-red.log`，修后GREEN `/tmp/workbook-defined-name-owned-history-green.log`，验证同名global和Third local保留、undo完整metadata map还原、redo及第二次删表。

真实三表浏览器`/tmp/workbook-defined-name-removal-owned-second-green.log` exit0：首次删除true且名称列表为空，undo完整恢复name/scope/ref，redo成功，再删Other=true，最终Third，pageErrors=[]。HTTP context/save/revision仍由probe提供，实际文件处理为Python；不能据此声明生产HTTP端到端或图表依赖已完成。纯UI静态脚本`smoke/workbook-defined-name-sheet-removal-built-smoke.mjs`已准备，等待统一构建。

Other局部解除引用同样完成真实保存闭环（`/tmp/workbook-defined-name-removal-dev-local-clear-green.log`，exit0）：保存先applyDefinedNames sets带`scopeSheetName:"Other"`，再删Source，修订2读回名称仍属于Other，存续表/styles字节一致。类型检查曾暴露新增真实测试`getDefinedNameMap`返回Nullable；测试map读取已以`?? {}`保留官方空map语义，生产未因该错误调整，最终类型检查随root统一验收。

## 最终静态产物验收

统一构建`/tmp/office-name-removal-word-natural-build.log` exit0、40.09s；同prefix预算和contract均exit0。生产/static冻结后按global、Other局部、owned连续删除顺序运行真实UI静态探针，未访问dev route或注入runtime。

- global：`NAME_REMOVAL_CLEAR_SOURCE=1 node smoke/workbook-defined-name-sheet-removal-built-smoke.mjs`，session99429 exit0，`/tmp/workbook-defined-name-removal-built-global-final.log`。
- Other局部：增加`NAME_REMOVAL_SCOPE=Other`，session68982 exit0，`/tmp/workbook-defined-name-removal-built-local-final.log`。
- 自有局部三表：`node smoke/workbook-defined-name-owned-removal-built-smoke.mjs`，session24749 exit0，`/tmp/workbook-defined-name-removal-built-owned-final.log`。

global/local均先右键标签删除并确定，拒绝后实际File undo/redo保持Source，localStorage/saveLabel保持；随后通过真实名称管理器更新DeleteDependency引用为Other!$B$1，再删除/undo/redo、草稿重载、Python保存及修订2重开。最终只剩Other，名称引用正确且局部名称scope仍Other，B1:B5=[1,2,3,4,5]，存续worksheet/styles字节相同；操作严格先applyDefinedNames再applySheetEdits。owned窄路径真UI删Source后等待同步，再删Other成功，最终Third，打开名称管理器无旧名称残留；该路径完整history另有前述真实dev与Univer证据。

global/local各333个JS实际HTTP200且SHA与磁盘一致，owned一次加载111个。三者资产身份一致：`lazy-workbook-main-CJ_l72AD.js`、`lazy-workbook-engine-BAKi6X21.js`、`lazy-workbook-structure-followers-BbV_9C8c.js`，pageErrors均为空。此结果关闭本轮定义名称删表原子性、普通全局/局部解除引用保存及自有局部名称事务缺口；不扩大为生产HTTP端到端或全部图表/未投影内置名称编辑已对齐。
