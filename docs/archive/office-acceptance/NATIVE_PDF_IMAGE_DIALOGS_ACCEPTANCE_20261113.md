# PDF 可视裁剪与去背景组件验收（2026-11-13）

固定 GenOffice 源 f8c17004fb730df11f0f743164ffd8b4281bb38c 的完整 ImageDialogs.tsx（CropDialog/CutoutDialog）、既有 cutout.ts/image-bake.ts。宿主保留数字裁剪/翻转/透明度，新增可视裁剪与去背景入口，复用 transformExistingImage PNG 替换操作；不新增发布签发机制。

## 实现范围

- 八方向裁剪手柄、框内移动、四侧键盘比例、Enter应用及Esc取消；容差滑块与真实背景移除预览。
- 嵌套原生dialog、焦点圈定/返回、低高度滚动与窄屏布局。独立审查发现取消按钮Enter误应用及IME快捷键误触，4个RED探针复现后修复并GREEN。
- 只读image-pixels API绑定已授权修订/源SHA/pageId/imageId/像素指纹，并要求既有bakeable能力；只渲染图像对象自身，绝不以整页截图冒充原图。
- 后端独立校验目标身份、严格Base64、真实PNG、字节SHA、正整数尺寸与实际尺寸。前端读取和应用时检查目标、草稿快照及世代；取消/切换/销毁/迟到回调不写草稿。

## 已有证据

持久目录 /home/junge/codex-evidence/smart_reporting/office-next-source-families-20261113/pdf。

- pixels-red.log / pixels-green.log：真实PDF目标像素和伪造来源/目标/页/指纹拒绝。RED是缺少export的功能缺失证据。
- visual-red.log → visual-green.log：新增控制器5例与受影响加载/数字烘焙9例，共14passed。
- ui-review-keyboard.log → ui-review-green.log：键盘4例RED修复；复验键盘4+控制器5=9passed。没有重复仓库完整测试。
- API回执11例、来源摘要1例、非PNG同摘要1例通过；HTTP13行为分轮通过（11passed，再仅复验失败2例）。真实PNG300×240，源文件/修订不变，未调用save。
- 隔离PDF CLI SHA256 aba3d5f8258652b3c31bffbceaab52de83da576e52523589dfbbceb9ee735e11，7354852bytes；api-runtime/build-identity.json记录全部输入。
- source browser裁剪已完成1440×900/640×360/390×320两dialog取消、八手柄拖动、键盘范围、UndoRedo/草稿恢复、实际PDF预览、一次save和实际download。独立pymupdf/pypdf证明目标裁剪、正文与另一图像保持；browser-crop-v4/independent-fidelity.json。
- source browser尚未全部通过：v4修订重开超时；去背景v1启动遇dev模块旧导出错误。保留失败日志，等待固定生产产物复验，不能据此声称完整浏览器验收已通过。

## 验收边界

API授权/修订/软验收告警使用显式fixture；真实运行编辑器、受控像素读取、原生Python/Node PDF修改、浏览器下载与独立文件读取。不是生产数据库、桌面Office或全PDF能力验收。来源不满足现有安全能力时明确禁用。下载仍保留validation.ok=false及具体原因，不标记验收通过。

最终冻结构建、HTTP资源SHA、去背景透明通道与新修订重开结果待追加。

## 冻结生产构建验收补充

最终 source-v2：4394个源文件，源manifest SHA256 fc493bcb2305db74aac56653de4fc5ffc1fd7ba4f41fad5ecabdb705fd05b872；无源漂移。TypeScript检查、Vite45.32秒构建、原有资源预算均exit0，没有提高预算；static717文件，manifest SHA256 7949df1457ac33345c20d4ba447bc26d0a922881f8812040838bf82d6f00e0a8。PDF engine255工作区输入全部与冻结源匹配。

裁剪与去背景分别完整通过frozen-crop/evidence.json、frozen-cutout/evidence.json，每条1次保存/实际下载，194次HTTP JS/CSS资源摘要全部匹配；三个viewport各两dialog动作可点/键盘焦点/取消不写入；鼠标手柄与数值Enter路径、UndoRedo/刷新草稿、真实PDF预览、新修订2重开、0浏览器错误。非阻断验收告警仍明确保留。

独立pymupdf/pypdf回读：裁剪4077bytes SHA256 6f0bab2173c6e2e70f7872a862a20e42a51d85f8b43b3985ac87b7ab675dbca8；目标范围[72,222,172,372]、PNG300×450。去背景5732bytes SHA256 e0a2fe6a627b19c46b0510381a212c89527966dd557c037c3ce68d413bd72d90；原范围保持、角像素alpha0/中心alpha255。两条正文与相邻图像像素均保持。root目视桌面裁剪与390×320去背景截图，布局及可见操作合格。

前述dev失败保留，不改写为绿色；正式固定构建完整通过提供最终证据。不代表全部PDF功能或真实生产权限系统验收。
