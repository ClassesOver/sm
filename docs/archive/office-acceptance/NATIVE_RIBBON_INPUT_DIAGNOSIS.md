# PPTX custom size: input failure diagnosis and acceptance

## Finding

The earlier failure did not establish an editor defect. With the same Playwright installation, the managed Chromium 140.0.7339.16 runtime retained a bare HTML input's initial value after `fill`, keyboard typing and direct CDP `Input.insertText`. Keyboard events were delivered but `beforeinput`/`input` were absent. No editor source, stylesheet, API or document engine was loaded in this control experiment. Setting the DOM value directly worked, but is not accepted as a substitute for real user input.

System Chromium 154.0.8037.57 passed the same bare-input and modal-input control: values changed and native `beforeinput`/`input` events fired. This isolates the observed failure to the tested browser/runtime combination; it does not identify a general Chromium 140 defect or establish which underlying runtime component is responsible. A full new-headless Chromium 140 binary reproduced the same input failure as its headless-shell binary.

No speculative editor workaround was retained. In particular, removing the hidden PDF preview's `src` did not resolve the failure and was reverted.

## Reproduction

From `smart_reporting/report_editor/frontend`, compare these actual binaries using the same checked-in baseline:

```sh
node --input-type=module <<'JS'
import { chromium } from 'playwright'
import { verifyBrowserTextInput } from './smoke/browser-input-preflight.mjs'
for (const executablePath of [undefined, '/usr/bin/chromium']) {
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
  try {
    console.log({ executablePath, baseline: await verifyBrowserTextInput(browser) })
  } catch (error) {
    console.log({ executablePath, version: browser.version(), error: error.message })
  } finally { await browser.close() }
}
JS
```

The PPTX smoke now performs this baseline before editor interaction, fails explicitly on unusable input, and allows an explicit executable selection. It does not silently fall back to another browser or set input values through JavaScript.

```sh
REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
PPTX_SMOKE_MODE=slide-size-custom node smoke/pptx-native-save-smoke.mjs
```

## Independent acceptance evidence

The command above passed on Chromium 154.0.8037.57. It exercises native input of 25 × 20 cm, both orientation switches without selecting a preset, Undo/Redo, save to revision 2, actual downloaded bytes, and browser reopening of revision 2. The source bytes remain unchanged. Both the native inspector and independent python-pptx readback report 9000000 × 7200000 EMU.

The first run with working input exposed an incorrect smoke expectation: it assumed the geometry of a fixed 16:9 resize. The corrected expectation is calculated from python-pptx's source dimensions and source shape geometry, scaled by the target dimensions. Both the independently read output geometry and native inspector geometry must agree. The assertion was corrected to match the resize contract, not removed.

Recorded successful run:

- Source SHA-256: `8ce3e9ad998743ad49666fe99739d1039c64d97fa0d0868c4149338ec93c9591`
- Download SHA-256: `8f1a6340ad7bab8ffb33ec2f97d217dfe6e1f5d1081273c83c04397cc51b301a`
- Revision: 2; size: 9000000 × 7200000 EMU; operation: `editSlides`.

Fixture bytes include generation-time metadata, so another run need not produce the same SHA. The smoke verifies source immutability and download identity within each run.

## Scope and remaining work

This browser fixture uses API route substitutes; it proves browser-to-real-file-engine behavior, not HTTP authorization or production persistence. See `NATIVE_RIBBON_HTTP_EVIDENCE.md` for separate real ASGI route coverage and repository substitutions. See `NATIVE_RIBBON_COMMAND_AUDIT.md` for fixed-upstream command comparisons and the resulting product fixes.

Only this custom-size slice has closed browser acceptance. Complete ribbon parity, a fresh clean/offline image, real production database concurrency and desktop Office interoperability remain unverified. Feature flags remain off; no deployment or merge was performed.


Source identities for the successful browser closure (SHA-256 of current local files):

| File | SHA-256 |
| --- | --- |
| `frontend/src/slides-main.ts` | `9516a68ba4336f5a5f58c40963ae5a6abef85e75c8a8e4f5b2750d0422e017df` |
| `frontend/src/slides-size-dialog.ts` | `91cc91cb30b5018270aca566a8c8a5e5e49896bae2b70247fc6f5d3e1548468b` |
| `native_office.py` | `8b52a117533d666c24eaef714ee12308e4dd90d0aba66394d340ca81356b5ef9` |
| `reporting/slides_engine/bridge/edit-pptx.ts` | `7c55d2249affb87f4a8377bbbb00384ff6b15bcb084ba8a60db790a2f6657f69` |

These changes sit above PR head `0017ff7a22cb7931eb8dc387b0eb98b14601d933`, base `d0a683c11a9b4c068c8d91fcf385fd7f040c17b9`. The fixed upstream reference is `genspark-ai/genoffice@f8c17004fb730df11f0f743164ffd8b4281bb38c`. No upstream implementation file was modified in this follow-up.
