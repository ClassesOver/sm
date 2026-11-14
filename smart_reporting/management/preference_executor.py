"""记录实际生成与回读实现身份；不把部署清单冒充视觉或字体证据。"""

import hashlib
import json
import os
import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path

from ..reporting.delivery.office_engine import bridge_execution


def _identity(path, *, relative_to=None):
    label = str(path.relative_to(relative_to)) if relative_to else str(path.resolve())
    result = {'path': label, 'exists': path.is_file()}
    if result['exists']:
        with path.open('rb') as stream:
            result['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def _converter_identity():
    # 和正式Word/Office预览的PATH选择顺序一致，不把名称或版本代替实际字节身份。
    office = shutil.which('libreoffice') or shutil.which('soffice')
    word = shutil.which('pandoc') or office
    selected = {'word': word, 'officePreview': office}
    return {role: _identity(Path(path)) if path else {'path': None, 'exists': False}
        for role, path in selected.items()}


def _font_identity():
    from ..preferences.workbook_adapter import FONTS

    faces = {}
    for family in sorted(set(FONTS.values())):
        for bold in (False, True):
            face = family + (':style=Bold' if bold else '')
            try:
                selected = subprocess.run(['fc-match', '-f', '%{file}', face], capture_output=True,
                    text=True, check=True, timeout=10).stdout.strip()
                faces[face] = _identity(Path(selected)) if selected else {'path': None, 'exists': False}
            except (OSError, subprocess.SubprocessError):
                faces[face] = {'path': None, 'exists': False}
    return {'selector': _identity(Path(shutil.which('fc-match') or 'fc-match')), 'faces': faces}


def _pdf_asset_identity(directory, entrypoint):
    # 沿用pdf_engine/src/main/wasm-path.ts的显式覆盖、Node原生模块解析及打包落点。
    override = os.environ.get('AGENT_REPORTING_PDF_WASM_DIR')
    resolved = True
    if override:
        paths = {name: str(Path(override) / name) for name in ('pdfium.wasm', 'hb-subset.wasm')}
    else:
        module = entrypoint if entrypoint.suffix == '.mjs' else directory / 'src/main/wasm-path.ts'
        packaged = directory / ('wasm' if entrypoint.suffix == '.mjs' else 'src/wasm')
        script = """const {createRequire}=require('node:module');
const {dirname,join,resolve}=require('node:path'); const {existsSync}=require('node:fs');
const req=createRequire(resolve(process.argv[1])); const packaged=process.argv[2];
const find=(name,module,secondary)=>{try{return req.resolve(module)}catch{}
 if(secondary){try{const p=join(dirname(req.resolve('harfbuzzjs')),secondary);if(existsSync(p))return p}catch{}}
 return join(packaged,name)};
process.stdout.write(JSON.stringify({'pdfium.wasm':find('pdfium.wasm','@embedpdf/pdfium/pdfium.wasm'),
'hb-subset.wasm':find('hb-subset.wasm','harfbuzzjs/hb-subset.wasm','harfbuzz-subset.wasm')}));"""
        try:
            result = subprocess.run(['node', '-e', script, str(module.resolve()), str(packaged.resolve())],
                cwd=directory, capture_output=True, text=True, check=True, timeout=10)
            paths = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            resolved = False
            paths = {name: str(packaged / name) for name in ('pdfium.wasm', 'hb-subset.wasm')}
    return {'overrideDirectory': str(Path(override).resolve()) if override else None, 'selectionResolved': resolved,
        'files': {name: _identity(Path(path)) for name, path in sorted(paths.items())}}


def executor_manifest():
    """包含实际 bundle/源码/部署覆盖目录；外部字体和转换环境仍需场景证据。"""
    from ..reporting.workspace import _report_runtime_package

    root = Path(__file__).resolve().parents[1]
    files = set((root / 'preferences').glob('*.py'))
    files.update((root / 'management').glob('preference*.py'))
    files.update((root / 'reporting/delivery').rglob('*.py'))
    files.update(root / path for path in (
        'reporting/trace/contracts_v1.py', 'reporting/trace/markdown_body.py',
        'reporting/workspace.py', 'report_editor/render_preparation.py',
        'reporting/host_workspace.py',
        'reporting/workflow/repository.py', 'reporting/workflow/read_guard.py',
        'report_editor/template_render.py', 'report_editor/template_source.py',
        'report_editor/template_provenance.py',
        'reporting/template_semantic_review.py', 'reporting/bootstrap.py',
        'reporting/workflow/runtime/template_semantics.py',
        'reporting/workflow/runtime/template_delivery.py',
        'reporting/workflow/runtime/base.py', 'reporting/workflow/runtime/publication.py',
        'report_editor/design_preview.py', 'report_editor/service.py',
        'report_editor/trace_revisions.py', 'report_editor/trace_sources.py'))
    files.update(path for path in (root.parent / 'pyproject.toml', root.parent / 'uv.lock') if path.is_file())
    runtime_package, runtime_digest = _report_runtime_package()
    bridges = {}
    for engine, script in (('slides', 'build-pptx'), ('workbook', 'cli'), ('pdf', 'cli'), ('doc', 'edit-docx')):
        directory, command = bridge_execution(engine, script)
        entrypoint = Path(command[-1])
        sources = set()
        for folder in ('bridge', 'packages', 'vendor', 'src'):
            sources.update(path for path in (directory / folder).rglob('*')
                if path.is_file() and path.suffix in {'.ts', '.tsx', '.js', '.mjs', '.cjs', '.json'}
                and not {'node_modules', '.git', 'dist'}.intersection(path.relative_to(directory).parts))
        sources.update(path for path in (directory / 'package.json', directory / 'package-lock.json') if path.is_file())
        executable = Path(shutil.which(command[0]) or command[0])
        bridges[engine] = {'root': str(directory.resolve()),
            'mode': 'bundle' if entrypoint.suffix == '.mjs' else 'source',
            'entrypoint': _identity(entrypoint, relative_to=directory),
            'executable': _identity(executable),
            'sourcesAndLocks': [_identity(path, relative_to=directory) for path in sorted(sources)]}
    converters, fonts = _converter_identity(), _font_identity()
    pdf_root, pdf_command = bridge_execution('pdf', 'cli')
    assets = _pdf_asset_identity(pdf_root, Path(pdf_command[-1]))
    issues = []
    if not assets['selectionResolved']:
        issues.append({'code': 'pdf_runtime_asset_resolution_failed', 'resource': 'pdf-wasm'})
    for role, identity in converters.items():
        if not identity['exists']:
            issues.append({'code': 'converter_identity_missing', 'resource': role})
    for face, identity in fonts['faces'].items():
        if not identity['exists']:
            issues.append({'code': 'font_identity_missing', 'resource': face})
    if not fonts['selector']['exists']:
        issues.append({'code': 'font_selector_missing', 'resource': 'fc-match'})
    for name, identity in assets['files'].items():
        if not identity['exists']:
            issues.append({'code': 'pdf_runtime_asset_missing', 'resource': name})
    for engine, bridge in bridges.items():
        for role in ('entrypoint', 'executable'):
            if not bridge[role]['exists']:
                issues.append({'code': 'bridge_identity_missing', 'resource': engine + '/' + role})
    return {'schemaVersion': 3, 'scope': 'generation_and_readback_implementation',
        'reportRuntimePackage': {'size': len(runtime_package), 'sha256': runtime_digest},
        'converters': converters, 'fontEnvironment': fonts, 'pdfRuntimeAssets': assets,
        'runtimeIdentityComplete': not issues, 'runtimeIdentityIssues': issues,
        'files': [_identity(path, relative_to=root.parent) for path in sorted(files)],
        'officeBridges': bridges,
        # 资源身份只用于漂移失效；仍须实际证明字体替换与可见版式。
        'separateEvidenceRequired': ['fonts_and_substitution', 'rendered_layout'],
        'libraries': {name: version(name) for name in
            ('python-docx', 'python-pptx', 'openpyxl', 'pymupdf', 'pypdf', 'matplotlib', 'weasyprint')}}
