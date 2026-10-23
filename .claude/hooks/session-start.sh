#!/bin/bash
# 云会话启动时安装依赖：Python（uv）、报告编辑器前端（npm）与报告渲染工具
# （LibreOffice Writer、pandoc、Noto CJK 字体）。幂等，已安装的部分直接跳过。
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# 报告渲染：WeasyPrint 出 PDF，pandoc 出 Word，LibreOffice Writer 做 Word 验收；
# 只有 libreoffice-core 时 LibreOffice 无法加载任何 DOCX。libharfbuzz-subset0 让 WeasyPrint
# 用 HarfBuzz 做中文字体子集化（缺失时回退 fontTools，每个字重约 3 秒）。
render_packages=(libreoffice-writer pandoc fonts-noto-cjk libharfbuzz-subset0)
missing=()
for package in "${render_packages[@]}"; do
  dpkg -s "$package" >/dev/null 2>&1 || missing+=("$package")
done
if [ "${#missing[@]}" -gt 0 ]; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "${missing[@]}"
fi

# 后端依赖（含 dev 组的 pytest、ruff）。
uv sync --no-install-project

# 报告编辑器前端（vitest、tsc）：按锁文件安装（npm ci 不改写 package-lock.json）；
# node_modules 已与锁文件一致时跳过。
frontend=smart_reporting/report_editor/frontend
if [ -f "$frontend/package-lock.json" ] && command -v npm >/dev/null 2>&1; then
  if [ ! -f "$frontend/node_modules/.package-lock.json" ] \
      || [ "$frontend/package-lock.json" -nt "$frontend/node_modules/.package-lock.json" ]; then
    (cd "$frontend" && npm ci --no-audit --no-fund)
  fi
fi
