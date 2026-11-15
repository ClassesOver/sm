# 原生 PPTX 完整 CutoutDialog 固定源验收记录（2026-11-13）

## 范围与结论

固定源 ref f8c17004fb730df11f0f743164ffd8b4281bb38c 的 CutoutDialog 完整实际功能族已接入并完成唯一正式 frozen-final-v3 浏览器验收，进程 exit0。源控件包含阈值、520px 预览、棋盘透明背景、百分比提示、原分辨率 PNG 应用及取消。固定源中的保留/移除画笔与局部撤销只是 TODO，本次未扩展。正式结果限定为显式原生文件夹具的 Cutout 路径，不冒称生产授权或整个 Python 环境冻结。

## 冻结身份

- 源码 manifest：5f915fbb9fd59ea46d19b980a43ccf120d7c42e199b46696a67665a227ad6e1d。
- 静态 Vite manifest：5658c601dbbba3447288e85c0da97914e99778719232d14c6ff1ce1f1bf01aa4。
- 实际编辑 runtime：68096527e6226734bbbe9b6c24dc42b2c71a4ff5b1af10589ab81e0bb5bde54a。
- 实际渲染 runtime：98552249029af7d5e4bd10c6f80bf7a03448a56df8e55cdffa9b816eddeb678f。
- 131 个产品 runtime 输入、150 个依赖及两项 runtime 输出均核对；v1 runtime 产品输入与 v3 manifest 一致，复用依据另见根 v3-input-compatibility.json。
- 浏览器收到的 152 个 JS/CSS 资源正文逐项与冻结 static bytes 核对，资源及浏览器错误为空。

## 实际验收

完整源预览阈值改变实际像素，取消不入草稿；应用生成一次 PNG 替换，既有 NativeDraft 单次撤销/重做有效；640×360 下滑块方向键与 Escape 有效。刷新恢复真实草稿后仅保存一次、下载一次。保存结果在新 context 以实际下载 bytes 重开，透明媒体身份一致，再次打开完整去背景预览有效，重开不追加保存/下载。

- 原始 fixture SHA256：8c05e0041379ca800162d16b324d63a436a9ac90ca475252ee7a83eee4850080。
- 实际下载 PPTX SHA256：8e4bc9ae6ec0f4304ec17077bbd77f7b3684139117e0033d48b9e81dbadaf1d0，68995 bytes。
- 新 PNG：838abee02eb4ce5e42e85c54f718ec84e15218eb91a015e47a15f6fbdfa9501a，1040×600 原分辨率，边缘 alpha0、主体 alpha255、封闭白色保留。
- 独立 ZIP/lxml、Pillow 与 python-pptx 回读确认 13° 旋转、原裁切窗口、框架、第二页共用原图、正文及讲稿保留；仅 slide1.xml 与其 rels 修改，新增 image2.png，其他包部件不变。透明像素底色不属于可见像素保留契约。

## Python 执行边界

复用 live .venv/PYTHONPATH 基础环境，13 次实际 Python 进程退出身份回执已保留。native_office、slides、slides_render、office_engine 四项实际调用路径文件均与 v3 冻结一致。写入沿 fixture → patch_office → ReportSlidesEditorService._run_engine → run_bridge(slides,edit-pptx)，渲染沿 render_pptx_tree → run_bridge(slides,render-pptx)，环境变量明确指定冻结 runtime。

reporting/delivery/pptx.py 被传递导入，运行期间并发 DPI 开发使文件 SHA 从 v3 e915291273639367d204d4ec219054a595b7787672e98d59f609d8f9e086d6da 变为 fe4fea5c263e0dc9d1190eef6790a568ce4e040e9a72ecf8073dae564ed05275。该漂移不隐去，也不据此重跑：静态调用图显示 fixture 不调用其 build_editable_pptx/DPI 函数。这里是静态调用图核对和进程退出文件身份记录，没有历史函数调用 trace，故不宣称整个 Python 环境无漂移。

## 证据位置

/home/junge/codex-evidence/smart_reporting/office-image-links-measure-20261113/pptx/browser/final-v3

- evidence.json：76dff731f41aad5b7b165559bb22ea7562a5e635ea985cc757e0ec700ab3469e。
- acceptance-summary.json、preflight-identity.json：最终结论与源/静态/runtime 身份。
- runner-adaptations.json：冻结 runner 的精确路径适配 diff 与 SHA；未修改产品或共享 static。
- python-execution-*.json、python-path-review.json：实际 Python 文件身份及调用图边界。
- fixture/downloaded.pptx、fixture/saved-journal.json、revision-reopen.png：实际下载、保存请求与新 context 重开。
- 早期 source-v1～v4 的浏览器/校验器失败保留；source-v5 为源阶段成功；本正式 final-v3 仅执行一次且 exit0，没有把事后修复改写为原始 PASS。
