"""Compare real DrawingML code with fixed source execution and Python colorsys."""
import colorsys
import hashlib
import json
import math
import random
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
ENGINE = REPO / 'smart_reporting/reporting/workbook_engine'
SOURCE_COMMIT = 'f8c17004fb730df11f0f743164ffd8b4281bb38c'


def run(source_repo, output):
    def original(path):
        return subprocess.check_output(['git', '-C', str(source_repo), 'show', f'{SOURCE_COMMIT}:{path}'], text=True)
    color = original('packages/pptx-engine/src/color.ts')
    utils = original('packages/pptx-engine/src/xml-utils.ts')
    # Execute original function bodies, without importing unrelated theme/parse modules.
    source = utils[utils.index('export type XmlNode'):utils.index('/** Decode numeric')]
    source += color[color.index('export function applyColorMods'):]
    rng = random.Random(190222)
    colors = ['#4472C4', '#7F0000', '#000000', '#FFFFFF', '#808080', '#C0504D', '#E97132']
    colors += [f'#{rng.randrange(0x1000000):06X}' for _ in range(25)]
    cases = []
    for hex_color in colors:
        h, lightness, s = colorsys.rgb_to_hls(*(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)))
        for mod in (0, 10000, 25000, 40000, 75000, 90000, 100000):
            for off in (0, 10000, 20000, 60000, 100000):
                channels = colorsys.hls_to_rgb(h, min(1, lightness * mod / 100000 + off / 100000), s)
                expected = '#' + ''.join(f'{math.floor(v * 255 + 0.5):02X}' for v in channels)
                cases.append({'hex': hex_color, 'mod': mod, 'off': off, 'python': expected})
    program = """
import {transform} from 'esbuild';
import {chartLabelColor} from './packages/xlsx-engine/src/chart-label-color.ts';
let input='';for await(const chunk of process.stdin)input+=chunk;
const data=JSON.parse(input),js=await transform(data.source,{loader:'ts',format:'esm'});
const original=await import('data:text/javascript;base64,'+Buffer.from(js.code).toString('base64'));
console.log(JSON.stringify(data.cases.map(c=>({
 original:original.applyColorMods(c.hex,{'a:lumMod':{'@_val':String(c.mod)},'a:lumOff':{'@_val':String(c.off)}}),
 local:chartLabelColor(`<a:srgbClr val="${c.hex.slice(1)}"><a:lumMod val="${c.mod}"/><a:lumOff val="${c.off}"/></a:srgbClr>`)
}))));
"""
    result = subprocess.run(['node', '--import', 'tsx', '--input-type=module', '-e', program], cwd=ENGINE,
                            input=json.dumps({'source': source, 'cases': cases}), text=True, capture_output=True, check=True)
    actual = json.loads(result.stdout)
    mismatches = []
    python_rounding = []
    for case, value in zip(cases, actual, strict=True):
        if value['original'] != value['local']:
            mismatches.append({**case, **value})
        if value['local'] != case['python']:
            differences = [abs(int(value['local'][i:i + 2], 16) - int(case['python'][i:i + 2], 16)) for i in (1, 3, 5)]
            assert max(differences) <= 1, (case, value)
            python_rounding.append({**case, **value})
    evidence = {'ok': not mismatches, 'cases': len(cases), 'sourceCommit': SOURCE_COMMIT,
                'sourceColorSha256': hashlib.sha256(color.encode()).hexdigest(),
                'sourceUtilsSha256': hashlib.sha256(utils.encode()).hexdigest(),
                'sourceMismatches': mismatches, 'pythonOneByteRoundingDifferences': python_rounding,
                'commentDiscrepancy': {'comment': '#2F5496', 'actualCodeAndPython': '#2F5597'}}
    output.write_text(json.dumps(evidence, indent=2))
    assert not mismatches, mismatches[:3]
    print(json.dumps({'ok': True, 'cases': len(cases), 'pythonOneByteRoundingDifferences': len(python_rounding), 'output': str(output)}))


if __name__ == '__main__':
    run(Path(sys.argv[1]), Path(sys.argv[2]))
