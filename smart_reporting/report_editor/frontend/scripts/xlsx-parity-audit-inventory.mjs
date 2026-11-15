/** Static audit CLI: verifies pinned source blobs and inventories declarations; never executes UI expressions. */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';
import { inspectUiSource } from './office-ui-inventory.mjs';
const argument = name => { const i = process.argv.indexOf(name); if (i < 0 || !process.argv[i + 1])
    throw Error('Required: --source-root <dir> --tree <json> --output-dir <dir>'); return path.resolve(process.argv[i + 1]); };
const sourceRoot = argument('--source-root'), treePath = argument('--tree'), out = argument('--output-dir');
const repo = fileURLToPath(new URL('../../../../', import.meta.url));
await fs.mkdir(out, { recursive: true });
const tree = JSON.parse(await fs.readFile(treePath, 'utf8')), manifest = [], sourceModules = [], localModules = [];
const sha256 = b => crypto.createHash('sha256').update(b).digest('hex');
const blob = b => crypto.createHash('sha1').update(Buffer.concat([Buffer.from(`blob ${b.length}\0`), b])).digest('hex');
function commands(text, file) { const ast = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS), calls = []; function visit(n) { if (ts.isCallExpression(n) && n.arguments.length) {
    const callee = n.expression.getText(ast);
    if (/(?:^|\.)(?:onCommand|runRibbonCommand|action|registerCommand|executeCommand)$/.test(callee)) {
        calls.push({ line: ast.getLineAndCharacterOfPosition(n.getStart(ast)).line + 1, callee, args: [...n.arguments].slice(0, 3).map(a => ts.isStringLiteralLike(a) ? { literal: a.text } : { expression: a.getText(ast).slice(0, 240) }) });
    }
} ts.forEachChild(n, visit); } visit(ast); return calls; }
for (const f of tree.tree) {
    if (f.type !== 'blob')
        continue;
    const file = sourceRoot + '/' + f.path;
    let b;
    try {
        b = await fs.readFile(file);
    }
    catch {
        continue;
    }
    if (blob(b) !== f.sha && b.at(-1) === 10 && blob(b.subarray(0, -1)) === f.sha) {
        b = b.subarray(0, -1);
        await fs.writeFile(file, b);
    }
    if (blob(b) !== f.sha)
        throw Error('unverified source bytes ' + f.path);
    manifest.push({ path: f.path, gitBlob: f.sha, sha256: sha256(b), bytes: b.length });
    if (/\.(tsx?|json|css|md)$/.test(file)) {
        const isCode = /\.tsx?$/.test(file), parsed = isCode ? inspectUiSource(b.toString('utf8'), file) : {};
        sourceModules.push({ file: f.path, sha256: sha256(b), ...parsed, commands: isCode ? commands(b.toString('utf8'), file) : [] });
    }
}
async function walk(dir) { const result = []; for (const e of await fs.readdir(dir, { withFileTypes: true })) {
    if (e.isDirectory())
        result.push(...await walk(path.join(dir, e.name)));
    else
        result.push(path.join(dir, e.name));
} return result; }
for (const file of await walk(repo + '/smart_reporting/report_editor/frontend/src')) {
    const rel = path.relative(repo + '/smart_reporting/report_editor/frontend/src', file);
    if (!/^(?:workbook[-.]|workbook-vendor\/)/.test(rel) || !/\.tsx?$/.test(file) || /\.(?:test|spec)\./.test(file))
        continue;
    const text = await fs.readFile(file, 'utf8');
    localModules.push({ file: path.relative(repo, file), sha256: sha256(Buffer.from(text)), ...inspectUiSource(text, file), commands: commands(text, file) });
}
const channelsText = await fs.readFile(sourceRoot + '/apps/sheets/src/shared/ipc-channels.ts', 'utf8'), channelsAst = ts.createSourceFile('ipc.ts', channelsText, ts.ScriptTarget.Latest, true), channels = [];
function ipc(n) { if (ts.isVariableDeclaration(n) && n.name.getText(channelsAst) === 'IPC_CHANNELS') {
    let value = n.initializer;
    if (ts.isAsExpression(value))
        value = value.expression;
    if (ts.isObjectLiteralExpression(value))
        for (const p of value.properties)
            if (ts.isPropertyAssignment(p) && ts.isStringLiteralLike(p.initializer))
                channels.push({ name: p.name.getText(channelsAst), channel: p.initializer.text, line: channelsAst.getLineAndCharacterOfPosition(p.getStart(channelsAst)).line + 1 });
} ts.forEachChild(n, ipc); }
ipc(channelsAst);
const desktopText = await fs.readFile(sourceRoot + '/apps/sheets/src/shared/desktop-api.ts', 'utf8'), desktopAst = ts.createSourceFile('desktop-api.ts', desktopText, ts.ScriptTarget.Latest, true), desktopMethods = [];
function desktop(n) { if (ts.isInterfaceDeclaration(n) && n.name.text === 'DesktopApi')
    for (const member of n.members)
        if (member.name)
            desktopMethods.push({ name: member.name.getText(desktopAst), line: desktopAst.getLineAndCharacterOfPosition(member.getStart(desktopAst)).line + 1, signature: member.getText(desktopAst).slice(0, 700) }); ts.forEachChild(n, desktop); }
desktop(desktopAst);
const appText = await fs.readFile(sourceRoot + '/apps/sheets/src/renderer/App.tsx', 'utf8'), appAst = ts.createSourceFile('App.tsx', appText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX), imported = new Map(), runtimeAdapters = [];
for (const n of appAst.statements)
    if (ts.isImportDeclaration(n) && n.importClause?.namedBindings && ts.isNamedImports(n.importClause.namedBindings))
        for (const specifier of n.importClause.namedBindings.elements)
            imported.set(specifier.name.text, n.moduleSpecifier.text);
function adapters(n) { if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && imported.has(n.expression.text) && /^(?:install|register)/.test(n.expression.text)) {
    const name = n.expression.text;
    runtimeAdapters.push({ name, sourceImport: imported.get(name) ?? null, line: appAst.getLineAndCharacterOfPosition(n.getStart(appAst)).line + 1, status: 'requires_semantic_comparison', note: 'An imported installer declaration is not proof of a missing local behavior or of runtime parity.' });
} ts.forEachChild(n, adapters); }
adapters(appAst);
await fs.writeFile(out + '/desktop-methods.json', JSON.stringify(desktopMethods, null, 2) + '\n');
await fs.writeFile(out + '/runtime-adapters.json', JSON.stringify(runtimeAdapters, null, 2) + '\n');
const known = tree.tree.filter(x => x.type === 'blob' && /^apps\/sheets\/src\/renderer\//.test(x.path)), saved = new Set(manifest.map(x => x.path)), excluded = known.filter(x => !saved.has(x.path)).map(x => ({ path: x.path, gitBlob: x.sha, size: x.size, reason: 'non-code asset outside the textual capability inventory' }));
const required = tree.tree.filter(f => f.type === 'blob' && (/^apps\/sheets\/src\/(?:renderer|main|preload|shared|ai|types)\/.*\.(?:tsx?|json|css|md|html)$/.test(f.path) ||
    /^apps\/sheets\/(?:README\.md|package\.json|docs\/.*\.md)$/.test(f.path) ||
    /^apps\/sheets\/native\/xlsx-engine\/src\/.*\.rs$/.test(f.path) ||
    /^packages\/xlsx-gateway\/src\/.*\.(?:tsx?|json)$/.test(f.path)));
const missing = required.filter(f => !saved.has(f.path)).map(f => f.path);
if (tree.truncated !== false || missing.length)
    throw Error('Incomplete source universe: ' + JSON.stringify({ truncated: tree.truncated, missing }));
const summary = { ref: tree.sha, treeTruncated: tree.truncated, sourceFiles: manifest.length, requiredSourceFiles: required.length, rendererFiles: known.length, rendererTextFiles: known.filter(x => saved.has(x.path)).length, excludedRendererAssets: excluded, localModules: localModules.length, sourceSites: sourceModules.reduce((n, m) => n + (m.sites?.length ?? 0), 0), localSites: localModules.reduce((n, m) => n + m.sites.length, 0), sourceCommandDeclarations: sourceModules.reduce((n, m) => n + m.commands.length, 0), localCommandDeclarations: localModules.reduce((n, m) => n + m.commands.length, 0), ipcChannels: channels.length, desktopMethods: desktopMethods.length, runtimeAdapters: runtimeAdapters.length, boundary: 'Static declarations, not distinct features, passing tests, or runtime parity; dynamic expressions/imported package internals need separate verification.' };
await fs.writeFile(out + '/source-files.json', JSON.stringify({ summary, files: manifest }, null, 2) + '\n');
await fs.writeFile(out + '/source-declarations.json', JSON.stringify({ boundary: summary.boundary, modules: sourceModules }, null, 2) + '\n');
await fs.writeFile(out + '/local-declarations.json', JSON.stringify({ boundary: summary.boundary, modules: localModules }, null, 2) + '\n');
await fs.writeFile(out + '/ipc-channels.json', JSON.stringify(channels, null, 2) + '\n');
await fs.writeFile(out + '/inventory-summary.json', JSON.stringify(summary, null, 2) + '\n');
console.log(JSON.stringify(summary));
