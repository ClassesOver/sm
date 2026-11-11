# MINIFS / MAXIFS 空匹配数值覆盖

固定来源：`/home/junge/pros/genoffice-source-full`，提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

- 原实现：`apps/sheets/src/renderer/ifs-empty-set.ts`，SHA256 `2cfcc098baca3f4ed4dc19d87fd01b59cd950b8d6d8b7c3c259b019420aa8f03`。
- 源安装：`apps/sheets/src/renderer/App.tsx:2414`，在 Univer 初始化后安装。
- 本地文件：`workbook-function-ifs.ts`，复用来源的原生执行器子类与结果修正，不另写 MINIFS/MAXIFS 条件计算。

本地实际 Univer 工作簿的 `MINIFS(A1:A3,B1:B3,"missing")` 与 MAXIFS 同式在修复前均返回空字符串，预期为数值 0。根因是本地 `@univerjs/engine-formula` 空集分支调用 `ArrayValueObject.create("0")`，产生 1×1 空字符串数组。

修正只识别这一数组形状及数组条件展开中的对应槽位；普通标量、数值、错误及干净数组沿用原结果。条件匹配、通配符、错误传播由原生执行器处理；不声称修复引擎所有错误条件语义。

相对来源的适配仅包括本地 runtime 类型、缺少 injector 的 headless 宿主 no-op、0ms 初始化重绑的 owner 检查、幂等 dispose、只恢复仍由本安装拥有的执行器，以及原来不存在执行器时的注销。真实 injector 异常直接传播。

主入口安装接口：`installIfsEmptySetFix(runtime) -> { dispose() }`。应在 `createUniver` 返回后、首次装载 workbook 数据前安装一次，在应用清理时先 dispose。0ms 重绑仅允许替换捕获的原执行器或相同原生 builtin 构造的执行器，保留后装第三方 owner。

独立验证证据：

- `/tmp/workbook-function-ifs-real-red.log`：真实工作簿空匹配 2/2 RED，实值为空字符串。
- `/tmp/workbook-function-ifs-real-green.log`：同两项真实工作簿 2/2 GREEN。
- `/tmp/workbook-function-ifs-conditions.log`：新增 2/2 GREEN，覆盖真实 0、负数、多条件、大小写、`?`、`~*`、匹配目标中的 `#DIV/0!`、尺寸不一致 `#VALUE!` 和数组条件空槽。
- `/tmp/workbook-function-ifs-lifecycle.log`：来源恢复、无原执行器清理、取消 timer、幂等卸载、初始化重绑及后装 owner 的原 3 项 GREEN。
- `/tmp/workbook-function-ifs-ownership-red.log` 和 `-ownership-green.log`：headless 与 timer 前后装 owner 的新增 2 项 RED → GREEN。
- `/tmp/workbook-function-ifs-final-bootstrap.log`：生命周期适配后只复核受影响的真实空集 2 项及初始化重绑 1 项。
- `/tmp/workbook-function-ifs-tsc.log`：只含本批 3 个 TS 文件的 strict 窄范围 tsc，exit 0。

未修改共享 registry、主入口、ribbon、Vite 或 static；未 build、运行项目完整测试或提交。
