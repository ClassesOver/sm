# GenOffice RTL 网格几何来源

固定源 https://github.com/genspark-ai/genoffice ，提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`；本地 `/home/junge/pros/genoffice-source-full`。Apache-2.0，随附原 LICENSE / NOTICE。

`rtl-grid-mirror.ts` 原样迁移 `apps/sheets/src/renderer/rtl-grid-mirror.ts`（1260行），SHA256 `0e8379603475372ac0f32e00c8d389992d39c8c9bb8d8d135da743e5bb6e1147`。该源模块只依赖四个官方 Univer 包，保留源 skeleton、绘制、hit-test、scroll、freeze viewport 原型适配，按每个 worksheet 的 rightToLeft flag 分流。没有用CSS水平翻转替代几何。

`rtl-grid-mirror.test.ts` 从固定源 `apps/sheets/tests/rtl-grid-mirror.test.ts` 选择纯网格32场景，修改import路径并去除依赖 WorkbookVisuals 的对象marker测试。涵盖mirror、freeze layout/split、collapse、scroll/reveal、border方向，不声明原对象拖拽测试也已迁移。

本地 `../../workbook-rtl.ts` 适配源 `sheet-rtl-view.ts`：每runtime注册缺失官方RTL command/mutation、共享install lease并仅释放自身注册；await原生async命令后校验真实flag和来源core，mutation变化时刷新同一active sheet render（含undo/redo）。无renderer的原生计算runtime保留状态，下一次渲染读取flag。源mirror prototype安装为原有进程级幂等行为，controller dispose不撤销共享几何补丁。

文件读写、主入口、草稿、最终browser hit-test及冻结窗格、对象定位仍须分别整链验证，不能从纯几何32项推定全量RTL完成。

2026-11-10 真实GUI适配差异：本地官方reCalculate不发active skeleton事件，源refresh调用在实际宿主只镜像cell坐标而不重建viewport。实际失败鼠标点右侧B1选M1后，本地adapter改用公开setCurrent({sheetId,commandId:SetWorksheetActiveOperation.id})触发官方freeze controller重建；vendor原字节保持。定向RED→GREEN及真实B2冻结鼠标/键盘/保存重开证据见NATIVE_XLSX_RTL_INVESTIGATION.md。
