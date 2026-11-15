# Native runtime/offline acceptance checkpoint

## Result and boundary

The standalone packaged-engine probe passed for DOCX, XLSX, PPTX and PDF in a read-only Docker container with `--network none`. Only `lo` was present. Python application modules and dependencies, three freshly packaged runtime directories, and newly built static resources were mounted read-only. This is **mounted-runtime-probe** evidence, not a fresh complete application image or production deployment certificate.

The same three packaged runtime directories were then used for the existing four-format ASGI upload/save/download/retry/reopen tests inside a second read-only, network-disabled container: **4 passed, 8.74s**, with the existing Python `imghdr` warning. Real route/middleware and actual packaged file engines execute; the test's in-memory repositories and forced validation exception remain substitutes. There is no production database or TCP/TLS assertion.

- Runtime image: `node@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d`.
- Image ID: `sha256:8700da48cc6592503feabf399d242414f932197c3b44f43970d2cbc5671e06b0`; Node: `v22.23.4`.
- Probe report and actual source/edited samples: `/tmp/pr190-native-offline-evidence/`.
- Complete runtime bundle digests, PDF WASM checks, static resource digests, source/edited SHA and independent readbacks are in that directory's `evidence.json`.
- Logs: `/tmp/pr190-native-offline-run.log`, `/tmp/pr190-packaged-offline-http.log`.

## What was verified

| Boundary | Independent evidence |
| --- | --- |
| Packaged JavaScript runtime | Built using the production packers; packaged directories contain no `node_modules`, `packages`, `bridge` or `src`; external Node configuration is rejected |
| Disabled features | All five environment feature flags remain false; disabled readiness requires no engine resources |
| Four-format resource readiness | Explicit temporary upload-resource probe passes, including the fixed PDFium/HarfBuzz WASM identities; it does not enable the application |
| DOCX | python-docx confirms replacement text and preservation of another paragraph |
| XLSX | openpyxl confirms edited value, original formula, number format and merged range |
| PPTX | python-pptx confirms text, custom 9000000×7200000 EMU size and scaled shape geometry |
| PDF | pypdf confirms reversed page order from distinct page sizes |
| Static resources | Built entry URLs are local/same-origin and their files exist; PDF.js cmaps/fonts/WASM resources have recorded hashes. This is not browser execution or a full JavaScript request-graph audit |

`verify_native_offline.py` fails on a nonisolated network namespace, invalid runtime/resources or incorrect file readback. On failure it returns nonzero and replaces a prior output report with `ok:false`. Two focused negative checks passed: connected-host rejection/stale-success replacement, and rejection of a missing entry resource. Dockerfile's two stale contracts were updated to include the third PDF engine and passed. Only affected checks were rerun.

## Reproduce the mounted probe

From the repository root, after installing the checked-in npm lockfiles, package the runtimes using the production commands:

```sh
(cd smart_reporting/reporting/slides_engine && npm run bundle:bridges -- --metafile=dist/metafile.json && node ../../../docker/package-office-engine.mjs . /tmp/pr190-native-runtime/slides)
(cd smart_reporting/reporting/workbook_engine && npm run bundle:bridges -- --metafile=dist/metafile.json && node ../../../docker/package-office-engine.mjs . /tmp/pr190-native-runtime/workbook)
(cd smart_reporting/reporting/pdf_engine && npm run bundle:bridges -- --metafile=dist/metafile.json && node bridge/package-runtime.mjs . /tmp/pr190-native-runtime/pdf ../../../docker/package-office-engine.mjs)
(cd smart_reporting/report_editor/frontend && npm run build && npm run build:slides && npm run check:budget && npm run test:budget)
```

Then run in the managed local Docker daemon. These mounts deliberately disclose the probe's host dependencies:

```sh
repo_root="$(pwd)"
python_runtime="$(dirname "$(dirname "$(readlink -f .venv/bin/python)")")"
mkdir -p /tmp/pr190-native-offline-evidence
env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
  docker --host=unix:///var/run/docker.sock run --rm --network none --read-only --tmpfs /tmp:rw,size=256m \
  -v "$python_runtime:$python_runtime:ro" \
  -v "$repo_root/.venv:/verify/venv:ro" \
  -v "$repo_root/smart_reporting:/app/smart_reporting:ro" \
  -v "$repo_root/scripts/verify_native_offline.py:/verify/verify_native_offline.py:ro" \
  -v /tmp/pr190-native-runtime/slides:/opt/reporting-slides-engine:ro \
  -v /tmp/pr190-native-runtime/workbook:/opt/reporting-workbook-engine:ro \
  -v /tmp/pr190-native-runtime/pdf:/opt/reporting-pdf-engine:ro \
  -v "$repo_root/smart_reporting/report_editor/static:/opt/report-editor-static:ro" \
  -v /tmp/pr190-native-offline-evidence:/evidence \
  -e PYTHONPATH=/app -e PYTHONDONTWRITEBYTECODE=1 -e MPLCONFIGDIR=/tmp/mpl \
  -e AGENT_REPORTING_SLIDES_ENGINE_DIR=/opt/reporting-slides-engine \
  -e AGENT_REPORTING_WORKBOOK_ENGINE_DIR=/opt/reporting-workbook-engine \
  -e AGENT_REPORTING_PDF_ENGINE_DIR=/opt/reporting-pdf-engine \
  -e AGENT_REPORTING_PDF_WASM_DIR=/opt/reporting-pdf-engine/wasm \
  -e AGENT_REPORT_EDITOR_STATIC_DIR=/opt/report-editor-static \
  node@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d \
  /verify/venv/bin/python /verify/verify_native_offline.py \
  --provenance mounted-runtime-probe --output-dir /evidence
```

For ASGI acceptance, use those same Python/source/runtime mounts and network flags, add the public test-only variables `AGENT_WORKSPACE_HMAC_SECRET=test-only-workspace-secret-0123456789` and `AGENT_REPORT_PUBLIC_BASE_URL=https://reports.test.invalid`, and replace the Python arguments with:

```sh
-m pytest /app/smart_reporting/reporting/tests/test_native_ribbon_http_roundtrip.py -q --tb=short -p no:cacheprovider
```

## Complete application image remains open

A real fresh build of the repository Dockerfile was attempted with official Python/Node/uv base images, official npm/PyPI indexes and optional BuildKit CA secret mounts. Both npm engine-packaging steps reached completion. The build stopped at copying the slides bridge source with `ResourceExhausted: no space left on device`: the managed daemon uses `vfs` and the writable workspace has 8 GB. No completed application image was produced. The build cache generated by this attempt was removed to recover workspace capacity; user source, the existing PostgreSQL image and running services were not deleted. Raw failure: `/tmp/pr190-clean-image-build.log`.

Dockerfile now supports optional `proxy_ca` (npm) and combined `system_ca` (uv) BuildKit secrets. TLS verification stays enabled and session certificates do not enter image layers. A rerun in an adequately sized managed environment can supply `--secret id=proxy_ca,src="$CODEX_PROXY_CERT" --secret id=system_ca,src=/etc/ssl/certs/ca-certificates.crt`; normal builds may omit both.

**Still open:** complete application image construction and source/hash comparison against it; installed-font/PDF-text probing in that image; image-hosted browser operation and full static request graph; production database transaction/concurrency and external host integration. The successful mounted probe closes none of those separate acceptance boundaries. No feature flag, deployment, merge or push occurred.
