# 工作表自有 drawing/chart/image 级联删除调查

本轮仅新增独立真实ZIP RED与实现计划，不修改生产，不bundle，不跑完整套件。保守拒绝仍是未对齐缺口，不能计作完成。

## 固定来源与实际调用链

源仓库`/home/junge/pros/genoffice-source-full` HEAD为`f8c17004fb730df11f0f743164ffd8b4281bb38c`。`packages/xlsx-gateway/src/gateway/xlsx-gateway.ts` SHA256 `748591515b74f2f5e8b25c40283b90b567640706eb97d2be015954717b390f6a`；`xlsx-sheets.ts` SHA256 `f1b20c4fd4868b39f4fe0e0c2c3d5a462343d87c84d9f091037f778249467679`。

`applySheetPlanToPackage`1962–1988为每个被删sheet计算owned闭包：`classifyRemovedSheetRels`先区分允许级联的根、可忽略关系及不支持关系；根target经`resolveRelTarget`解析，遍历存在的part及其关系part，仅沿内部关系继续，visited避免环。

1992–2017共享保护不是简单“这个part从被删sheet可达就删除”。先排除将消失的sheet/owned关系part，然后扫描包内全部存续`.rels`（含包根关系），任何incoming指向候选删除part都将该part加入keepQueue；从删除集合拉回该part、其关系part以及内部子树。共享drawing一旦保留，其chart/image等后代必须一起保留。

2039–2047图表依赖检查只跳过最终确定会消失的chart。chart即使原来属于被删sheet，若被存续incoming保留，仍须检查其公式；不能因最初owner归属而忽略依赖。2094–2100在全部校验完成后才移除sheet、sheet rels和最终owned集合。2157–2169清理每个被删part的ContentTypes Override；按扩展名共享的Default项保留，不因一个image删除就删png Default。

`xlsx-sheets.ts`允许的owned根为drawing/vmlDrawing/comments/threadedComment/ctrlProp/table/image；hyperlink/printerSettings可忽略，external不遍历；pivotTable、slicer、OLE及未知根仍拒绝。`resolveRelTarget`另验证空路径、URI/UNC、NUL、百分号解码和包根越界。源parseRelationships为无前缀自闭标签正则；若适配本地namespace-aware OPC读取，应明确是兼容加强，不伪称来源已有全部namespace能力。

## 本地精确差距

当前`packages/xlsx-engine/src/sheet-ops.ts::applySheetEdits`在删除任何part前调用`sheets-edit.ts::assertSheetRemovable`，任何内部drawing关系直接拒绝“charts or images”。因此尚未计算owned闭包、存续incoming或共享保留子树。

随后扫描所有匹配`xl/charts/chart[0-9]+.xml`的chart，不区分真正消失与存续；即使只撤销blanket拒绝，自己将删除的chart读自己的Source仍会被误拒。删除阶段仅移除worksheet及其.rels，ContentTypes仅删除worksheet Override；直接放行会残留drawing/chart/image及其Override。现有ZIP assembler支持声明removedEntries，可复用，无需新打包器。

前端已有actual OPC sheet→drawing→chart来源预检，可发现存续sheet图表引用；helper跳过被删sheet自身并不等于引擎级联完成。共享drawing若仍从Other可达，应继续作为Other来源检查。unowned chart仍保守扫描。级联计划与前端owner来源必须使用一致的实际关系身份，不能信任客户端传入raw、live空图列表或仅按`chart1.xml`文件名猜所有权。

## 新增真实RED

独立`tests/owned-drawing-delete-investigation.test.ts`使用openpyxl真实两表工作簿：Source拥有BarChart和PNG，Other保留常量。共享case通过真实ZIP关系重绑，而非mock引擎。

首次只运行该新文件（session62601 exit1，`/tmp/owned-drawing-delete-investigation-red.log`），3项真实RED：

1. 独占chart/image：预期删除Source、sheet关系、drawing及drawing关系、chart、media，移除对应Override而保留png Default；Other worksheet/styles字节保真。实际在drawing blanket拒绝。
2. 共享media：Other有独立drawing且关系指向同一image1.png；应仅删Source独占chart/drawing，保留共享media、Other wiring及字节。实际同样被blanket拒绝。
3. 共享drawing：Other的真实drawing引用指向Source drawing，chart仍读Source；应因存续chart依赖拒绝。当前拒绝原因仍是“不支持drawing”，没有走到共享闭包和依赖校验，不能计作该保护已实现。

随后只增跑第4项共享drawing整子树允许控制（`/tmp/owned-drawing-delete-shared-subtree-red.log`）：chart改读Other，应保留drawing、drawing关系、chart、media字节及chart/drawing Override，允许删Source。该控制用于证明keepQueue必须递归保留子树。

## 最小实现计划与验证门槛

1. 在`sheets-edit.ts`或单独`sheet-owned-parts.ts`复用/移植来源关系分类与闭包计划。产出最终removedParts，不直接写ZIP。先收集所有被删sheet根，再统一扫描存续incoming并递归keep，支持多表同时删除及环；所有校验在assembler之前完成。实际OPC namespace/路径解析优先复用现有安全解析，不能新增按后缀信任任意外来Type的宽泛授权。
2. `sheet-ops.ts`替换blanket owned拒绝为计划；图表依赖扫描只跳过最终removedParts内chart；其余worksheet/name/chart依赖继续拒绝。移除sheet/rels和最终owned entries，更新workbook rels及每个删除part Override，保留Default与存续字节。未知sheet根关系继续拒绝，不能为了放行drawing一并放行pivot/OLE等。
3. 新测试先完成上述4条，再增最小安全控制：多被删owner共享part、环、external不遍历、未知/pivot拒绝、encoded/relative/absolute合法路径、越界/missing/malformed来源、存续关系指向shared chart子树、多个同名media路径、非标准chart文件名。缺失来源不得悄悄授权删除；源代码跳过missing是来源事实，本地若更严格需明确披露。
4. 前端不靠临时忽略预检绕开保存。以真实三表case验证首次删除前完整预检、owned图表删除→undo恢复name/scope/实际图表来源→redo→草稿重载→Python保存→修订重开；shared media/shared drawing需证明存续实际资产身份和字节不变。若Univer不投影默认namespace chart，undo应通过仍绑定实际原始包/结构基线恢复来源，而不是从空snapshot推断丢弃。此项尚未执行，不宣称前端闭环。

最低修改面：engine`sheets-edit.ts`（分类/ContentTypes helper，或新owned planner）、`sheet-ops.ts`（整合最终删除集合）、独立测试；如需共享关系工具才单独提取小型OPC helper。frontend`workbook-main.ts`/`workbook-chart-source.ts`仅在证据显示删除undo或source缓存不能保持owner身份时最小调整，并由root独占。bridge/Python沿现有applySheetEdits调用不另造轮子；新增窄Python真实保存对照即可，不重跑完整套件。

表格、VML、comments等来源同属owned分类，但本轮实际RED仅chart/image/drawing，不应因计划提及而宣称全部satellite已验收。发布/下载签发链路不在本轮修改范围。

## 获授权后的最小 planner 实现

root随后授权实现独立helper，`src/sheet-removal-parts.ts`现提供：

- `planSheetRemovalParts(source:EntrySource,removedSheetPaths:readonly string[]):Promise<{removedParts:ReadonlySet<string>}>`：返回最终satellite及其关系parts，不含worksheet及worksheet.rels，后两者由root现有sheet删除统一处理。
- `removePartOverrides(xml:string,removedParts:ReadonlySet<string>):string`：支持同时传worksheet与satellite路径，验证ContentTypes namespace，仅剔除精确PartName的Override，保留Default和其他原始字节。

planner移植来源闭包→全部存续incoming→keep子树算法；XML使用既有saxes做namespace身份验证，root owned类型仅允许完整office relationship URI。支持transitional/strict package和office URI，合法别名前缀和百分号编码target；external不遍历；重复ID、非法TargetMode、DOCTYPE、畸形XML、外来关系namespace、未知内部sheet根关系、编码错误/包根越界/URI伪内部target及缺失owned part均明确拒绝。对存续incoming不按Type猜所有权，只要实际内部关系指向候选就保留，含包根关系。原始非修改parts不重写，helper本身不做ZIP mutation。

相比固定源正则parseRelationships及missing part跳过，namespace/路径/身份完整性和missing拒绝属于本地兼容及安全加强；未把其误写为固定源已有能力。strict URI支持也明确是适配能力。内部子树仍依来源算法沿全部内部关系求闭包，未知sheet根不放行。

helper缺失RED `/tmp/sheet-removal-parts-helper-red.log`后，13项GREEN `/tmp/sheet-removal-parts-helper-green.log`。随后仅新增运行7项安全控制GREEN `/tmp/sheet-removal-parts-safe-controls-green.log`：strict office URI、package-root incoming保完整子树、重复ID、encoded UNC/NUL/非法编码、DOCTYPE、prefixed paired Override精确移除及foreign namespace拒绝。root负责sheet-ops集成并重跑独立4条真实ZIP RED；此处不将helper绿视为保存/前端验收已完成。

## root集成与后续浏览器准备

root已将planner接入`sheet-ops.ts`：仅removals非空时求闭包，替代旧blanket调用；依赖检查和rename chart循环均跳最终removedParts，删除条目及所有删除part Override统一处理。原4条真实ZIP RED现GREEN（`/tmp/owned-drawing-delete-integrated-green.log`，root执行）。本agent只增跑rename surviving Other→Kept同时删除Source的组合控制，`/tmp/owned-drawing-delete-rename-combination.log`1通过/4未选，确认最终剩Kept且owned chart/drawing消失。

集成只读review确认removedParts在全部依赖检查之前计算，实际ZIP mutation在检查之后；shared incoming对子树保留覆盖package根关系，多owner和环有helper证据，unknown根未放行，ContentTypes foreign namespace不会按字面Override误删。未修改非涉及parts。

纯UI静态脚本`smoke/workbook-owned-drawing-delete-built-smoke.mjs`（4234）已准备且node --check0：默认exclusive或`OWNED_DRAWING_MODE=shared-image`检查真标签删除→undo/redo→草稿重载→真实Python保存→rev2；Python独立遍历所有内部rels核对目标存在、ContentTypes所有Override核对part存在，独占chart/drawing清理、共享media/Other drawing wiring保留，Other/styles字节保真。`OWNED_DRAWING_MODE=shared-drawing`仅检查存续Other仍读Source的原子拒绝、history/draft原状。尚未运行最终build，不把脚本准备当成浏览器验收通过。

### 集成范围审查提醒

源白名单也包含table，但源gateway2069–2091另外读取最终将删除table的displayName，检查存续worksheet结构化引用及存续defined names token。仅集成owned planner而不移植该守卫，会把原先table blanket拒绝扩大为可删除，遗漏`SUM(Table1[Amount])`这类没有`Source!`字样的依赖。已通知root：本轮drawing/chart/image范围应保持未验收table的原拒绝，或以独立table依赖实现与真实RED闭环，不能把白名单放行等同于全部satellite语义完成。源另有存续pivotCacheDefinition源sheet检查，本轮drawing证据不覆盖该独立边界。

## 表格结构化依赖守卫补齐

root接受范围审查并授权在同一新helper追加`assertRemovedTableDependencies(source,removedParts,survivingWorksheetPaths,workbookXml,removedLocalIds):Promise<void>`，由sheet-ops在mutation前await。仅扫描最终removed的`xl/tables/*.xml`，读取displayName/name；现有table-read未导出单纯displayName读取函数，因此复用共享XML attribute/text decoder，最小移植固定源token算法，不新增公式parser。

worksheet按原始XML大小写不敏感`TableName[` includes检查；defined names正文decode后同样检查，被删sheet的local scope跳过。该行为如实保留来源保守token语义（包括可能的字面量匹配），未伪称语义消歧全部完成。非最终removed table不检查。

独立真实openpyxl Table ZIP测试`tests/owned-table-delete-dependencies.test.ts`7项缺失export RED（`/tmp/owned-table-delete-dependencies-red.log`）后GREEN（session15196 exit0，`/tmp/owned-table-delete-dependencies-green.log`）：Other结构化公式case-insensitive拒绝、global与Other local名称拒绝、Source自有local忽略、无依赖/其他table允许、保留table不检查。仅运行新增文件，不重复完整套件。

该函数保护文件删除计划，不等同于前端实时删除已经具备table依赖原子预检；前端如尚未接可信table来源，应作为独立边界报告，不能拿保存晚拒绝冒充UI原子拒绝。本轮绘图浏览器fixture没有table。

root在sheet-ops接入await后，仅新增运行真实保存链调用控制1项GREEN（session58114 exit0，`/tmp/owned-table-delete-integrated-green.log`，1通过/7未选）：Source拥有SalesData，Other为SUM(SalesData[Amount])，实际applySheetEdits拒绝且错误含SalesData。没有重复无依赖允许或绘图4项。前端table结构化依赖的原子拒绝仍单列未完成。
