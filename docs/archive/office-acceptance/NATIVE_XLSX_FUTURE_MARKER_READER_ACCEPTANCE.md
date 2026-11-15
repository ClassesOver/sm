# XLSX 未来函数存储标记读取

此项是独立reader缺口：本地 `workbook-write.ts:34` 用 withFutureFunctionMarkers 将 MINIFS/MAXIFS 等写成 `_xlfn.MINIFS`，但 `workbook-read.ts:204` 把带标记公式直接交给编辑器，导致函数注册表匹配失败（main初载#NAME由root验证）。这与IFS空集求值无关，不属于其修复证据。

固定源 `/home/junge/pros/genoffice-source-full` HEAD 为 f8c17004fb730df11f0f743164ffd8b4281bb38c，工作树干净。固定源 gateway/xlsx-gateway.ts:3517 同样直读公式；future-functions文件头说明由 sidecar 在读取时剥标记。本地浏览器没有sidecar，因此必须补对应解码。固定源 gateway/future-functions.ts:235 的 functionCalls 已按token扫描并跳单双引号，识别 `_xlfn.`、`_xlfn._xlws.` 和单独 `_xlws.`；apps/sheets/src/renderer/formula-functions.ts:9、:31、:50 提供STORAGE_MARKERS及转义引号/括号区域跳过，保护字符串、引用和structured refs。

最小实现：仅在本地future-functions.ts新增withoutFutureFunctionMarkers，复用上述扫描规则，跳过双引号字符串、单引号sheet名、嵌套方括号；只有后接左括号的完整标识符才去掉开头存储marker，保持函数大小写、空白和其他公式字节。reader在XML解码之后调用它。withFutureFunctionMarkers、spillsDynamicArray以及writer行为未改，未替换整helper、未改前端vendor或主审计。

独立真实ZIP测试 `packages/xlsx-engine/tests/future-marker-reader-parity.test.ts` 首次9项全RED（实际读取仍含marker），实现后9项GREEN；扩展为14项，与CSV受影响回归9项合计23项GREEN。覆盖MINIFS/MAXIFS真实writer→ZIP marker→reader→再保存重开无双marker，_xlfn._xlws与单独_xlws、大小写与空白、XML编码和双写转义引号、含marker字符串和quoted sheet/defined name/structured reference不改。日志 `/tmp/xlsx-future-marker-reader-red.log`、`/tmp/xlsx-future-marker-reader-green.log`、`/tmp/xlsx-future-marker-reader-green2.log`。engine包tsc退出0（`/tmp/xlsx-future-marker-reader-tsc.log`）。不把这些ZIP测试计作真实Excel/桌面求值或main GUI验收。

固定源SHA256：

| 文件 | SHA256 |
| --- | --- |
| packages/xlsx-gateway/src/gateway/future-functions.ts | e20d15a15a949bba348297d741e7887c75b6369f2a0748fe25dfa8b51d08cfc6 |
| packages/xlsx-gateway/src/gateway/xlsx-gateway.ts | 748591515b74f2f5e8b25c40283b90b567640706eb97d2be015954717b390f6a |
| apps/sheets/src/renderer/formula-functions.ts | d72fb02a0d2b635c4aeb9b63035d3ec64b9ceb2c57af4e3974f17ab9b2c2b57c |

本地最终future-functions.ts SHA256 `f5e1d74944bca68b140c3bcb6c2968a6f29386ed22cc580e9377e89d4e914377`；workbook-read.ts `cc1bdd61a571d0d799882501a23f92c0f03ceb2c43d353fc7e0e2ab6263a5a57`。来源manifest及统一构建/main实际求值由root登记与验证。


独立审查补例：结构化引用列名的apostrophe可转义后续括号；固定源renderer的skipBracketed亦未覆盖。真实ZIP `SUM(Table1[Col']_xlfn.MINIFS(A1)])` 先RED，证明列名内marker被错误剥离（`/tmp/xlsx-future-marker-escaped-bracket-red.log`）。本地最小补充仅在方括号区域遇apostrophe时跳过下一字符，使转义括号不改变层级，外部MAXIFS仍正常解标记。增加2个negative后独立ZIP共16项GREEN，tsc退出0；日志 `/tmp/xlsx-future-marker-escaped-bracket-green.log`、`/tmp/xlsx-future-marker-escaped-bracket-tsc.log`。writer仍未改变；CLI须root按新helper重新bundle。
