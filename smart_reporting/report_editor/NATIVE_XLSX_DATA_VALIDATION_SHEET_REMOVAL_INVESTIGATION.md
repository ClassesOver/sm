# 数据验证：被引用工作表删除的原子性调查

本轮只新增独立测试、真实浏览器探针和本文档；未修改生产、manifest 或构建产物。选取无任何 CF、仅存在数据验证（DV）引用的工作簿，避免将 CF 的已通过结果外推到其他依赖。

## 来源与引擎对照

固定 GenOffice 提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `packages/xlsx-gateway/src/gateway/xlsx-sheets.ts` 明确约定 referenced-removal fail closed。其 `worksheetReferencesSheet` 扫描普通公式与 formula1/formula2；DV 跨表公式因此应阻止被引用表删除，而不是转为 #REF。源文件 SHA-256：`f1b20c4fd4868b39f4fe0e0c2c3d5a462343d87c84d9f091037f778249467679`。

本地 `sheet-ops.ts` 在 ZIP 修改前调用同名扫描，保留拒绝契约。独立测试 `packages/xlsx-engine/tests/data-validation-sheet-removal-investigation.test.ts` 共 **4 通过**（`/tmp/dv-sheet-removal-engine-investigation.log`）：大写和小写 DV 范围引用均拒绝；列表字符串字面量与外部工作簿引用允许，存续工作表 XML 完全不变。本轮未发现引擎 DV 扫描缺口。

## 真实浏览器 RED

探针 `frontend/smoke/workbook-dv-sheet-removal-gap-probe.mjs` 使用真实 openpyxl 文件、Vite 端口 4225 和官方 `sheet.command.remove-sheet`。Other 的唯一数据验证为 B1:B4 的 list，formula1 为 `=Source!$A$1:$A$5`，没有 CF。

`/tmp/dv-sheet-removal-browser-investigation.log` 记录：

- 删除返回 true，名称列表变成 `["Other"]`。
- DV formula1、uid、范围和选项保持原状，引用已不存在的 Source。
- undo 返回 true 恢复 Source；redo 再次删除 Source，DV 仍旧引用。
- 随后页面显示 `本地草稿暂未更新：工作表 "Other" 的公式仍引用 "Source"，已拒绝删除。`
- 页面异常列表为空，原子拒绝断言实际失败。

现有 `installDataValidationStructure` 对删除调用的前置检查仅为 CF 检查与 root 提供的 CF 来源回调。其 DV 公式迁移分支只处理行列结构或工作表改名，不能推定删除依赖也受到前置保护。因此这是独立于 CF 的实际 UI/引擎语义不一致：界面和历史已变，后端才拒绝草稿。

## 最小后续范围

1. 删除事务执行任何 mutation/follower/history 前，检查存续表的当前 DV formula1/formula2；复用 `formulaReferencesSheet`，保护字符串、外部簿及大小写边界。当前编辑新加引用必须被检测，不能只看初始文件。
2. 不完整或未投影 DV 来源应依据实际文件 XML 校验；来源缓存必须绑定实际模型与最新结构签名，禁止信任客户端 raw 字段。
3. 用户已清除/修改当前 DV 依赖后，应允许删除。保存时先持久化存续表当前 DV，再调用原有文件删除验证；只加前置拒绝仍可能使“清除后删除”在旧源依赖上失败。
4. 定向回归覆盖 formula1/formula2、live 新增/清除引用、被删表内部依赖排除、undo/redo/draft 原子性和真实保存；普通单元格公式、定义名称及图表需另行验证，不在本次 DV 证据中宣称完成。

本次只记录未修复的前端 RED，不修改既有 CF 路径，不重跑其完整测试。

## 前端预检与开发态保存闭环

新增独立 `workbook-dv-sheet-removal.ts`，复用 `formulaReferencesSheet` 检查存续live DV formula1/formula2。list无等号文本按来源writer视为常量，custom/数值类无等号公式仍扫描；精确当前workbook id限定符经共享rename公式语义归一本簿，字符串及其他外部簿保留。incomplete/readOnlyReason来源仅抽实际raw的标准/x14 dataValidations块；排除旧普通单元格及CF，不认识的DV前缀明确返回来源无法完整核对，不伪称无依赖。collector在任何原有collector/base mutation/history前调用DV检查，与既有第三source callback共用原子拒绝入口。

helper初模块缺失RED `/tmp/workbook-dv-sheet-removal-helper-red.log`；bare custom/decimal公式专项RED `/tmp/workbook-dv-sheet-removal-bare-red.log`，未知namespace专项RED `/tmp/workbook-dv-sheet-removal-namespace-red.log`。最终helper15项通过 `/tmp/workbook-dv-sheet-removal-helper-final-green.log`；含collector依赖拒绝-before-original的定向15项通过 `/tmp/workbook-dv-sheet-removal-target-green.log`。类型检查 `/tmp/workbook-dv-sheet-removal-frontend-types.log` exit0。

4226开发态探针默认 `/tmp/workbook-dv-sheet-removal-dev-refusal.log` exit0：实际删除返回false，sheet names、DV uid/公式/范围/选项保持原状，undo/redo均false，localStorage草稿与saveLabel不变，无保存请求且pageErrors=[]。`DV_REMOVAL_CLEAR_SOURCE=1` `/tmp/workbook-dv-sheet-removal-dev-clear-source.log` exit0：先拒绝，再通过官方removeRule mutation清除DV，允许删除、undo/redo、draft reload、实际Python patch/openpyxl保存及修订2重开；payload严格先replaceSheetDataValidations Other[]，再applySheetEdits移除Source，剩余values及styles.xml字节保留。清除使用官方mutation的开发态证据不替代真实面板操作。

root main负责实际ZIP raw的模型/结构签名绑定及DV-before-removal持久化顺序。context/save/revision HTTP由probe提供、文件处理为真实Python，不宣称生产HTTP端到端。4227纯UI脚本 `smoke/workbook-dv-sheet-removal-built-smoke.mjs` 已准备，走真实DV面板删除与实际标签删除入口，待统一build+预算READY后验收。

## 最终纯UI静态验收通过

root统一 `/tmp/office-dv-removal-build.log` exit0（41.92s），对应budget/contract exit0且未提高cap后，`DV_REMOVAL_CLEAR_SOURCE=1 node smoke/workbook-dv-sheet-removal-built-smoke.mjs` 一次完整exit0，证据 `/tmp/workbook-dv-sheet-removal-built-final.log`。

完全不注入或访问runtime：标签右键删除/确定先拒绝，真实File undo/redo后Source仍在，localStorage草稿和saveLabel不变；再通过Data→数据验证面板hover删除DV，标签删除、undo/redo、draft reload、实际Python patch/openpyxl保存、修订2重开全部通过。保存严格先replaceSheetDataValidations Other[]再applySheetEdits删除Source；实际文件只剩Other且DV为空，values1..5和styles.xml字节保留，pageErrors=[]。

333个实际JS响应均HTTP200并与磁盘SHA256匹配：main `lazy-workbook-main-E1BmN5bO.js`，engine `lazy-workbook-engine-DHUBPuWA.js`，collector `lazy-workbook-structure-followers-DBJhCmtV.js`。本验收完成DV删除引用原子性及解除依赖保存闭环，不扩大为普通单元格公式、图表、定义名称等全部删除依赖已对齐。

## 后续原生 Python 验收

新增独立文件 `reporting/tests/test_workbook_data_validation_sheet_removal.py`，以真实 openpyxl ZIP 经 `patch_office` 调用现有打包 engine，**18 通过**（`/tmp/dv-sheet-removal-native-python.log`）：formula1/formula2 × 本地表名/小写/quoted 共 6 拒绝；两字段 × Other 引用/字符串/quoted 和 unquoted 外部簿共 8 允许；两字段 × 修改为无依赖 DV 或清空 DV 再删除共 4 成功。允许删除时存续 sheet2.xml 与 styles.xml 字节相同；替换时只允许 DV 节点变化，其他 XML、values、font 与 fill 保留。只运行新增文件，未改 engine 生产代码；该证据不替代前端原子预检验收。

不完整来源形状已确认：`SheetDataValidationModel` 为 `{rules, readOnlyReason?}`，没有 sourceXml，且解析失败前可能已加入部分 rules；前端遇 readOnlyReason 整表不投影。原始 XML 必须从实际文件缓存，按模型身份和当前结构签名取用。标准 x14 DV 公式为 `<x14:formula1/2><xm:f>…</xm:f></x14:formula1/2>`，来源拒绝扫描应包含此形状。未知命名空间/节点未被解析则不得从空 live rules 推断无依赖。完整 live 规则的引用带 `=`，list 常量已经去引号且无 `=`；直接扫描常量文本会将包含 `Source!A1` 的列表误判为公式引用。
