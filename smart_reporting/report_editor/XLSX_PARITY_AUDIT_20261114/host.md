# Desktop IPC → local Web host audit

All76 fixed-source channels are assigned below. An IPC name is not a feature or a requirement to duplicate Electron transport. `host_boundary` remains open in full user-facing parity, while a deliberate permission boundary must not be removed automatically. Current static source/target inspection only; no runtime IPC/production authority verification. Source: `apps/sheets/src/shared/ipc-channels.ts`, `desktop-api.ts`, `src/main/sheets-main.ts`, preload; local native.py/native_api.py/workbook.py/native_office.py and frontend workbook-main.ts. Exact channel lines: ipc-channels.json and host-channel-map.json. DesktopApi methods also include inherited shell methods beyond these channels: desktop-methods.json.

| Group | Status | Exact channel names | Remaining behavior / boundary | Local evidence |
|---|---|---|---|---|
| open | host_boundary | selectWorkbook | native workbook attachment/revision context replaces desktop path picker; general desktop-open scope is absent | native.py, workbook.py, frontend/src/workbook-main.ts |
| encryption | missing | openEncryptedWorkbook updateWorkbookPassword | encrypted-open/password-change host missing; see core protection row | core.md |
| merge | done_bounded | selectWorkbooksForMerge openWorkbooksForMerge | manual merge upload/planner exists; complex object limits remain | data.md |
| indexed-read | partial | readWorkbookRange readWorkbookFormulas findWorkbookCells readWorkbookRowOutline | in-memory native workbook reads exist; source disk/chunk lazy query host differs | storage.md:S01, data.md:F12 |
| sidecar-lifetime | host_boundary | sidecarCrashed reopenWorkbook closeWorkbook | finite local CLI jobs/browser lifetime differ from long-lived Rust indexed sessions | storage.md:S09 |
| recalculation | partial | recalcWorkbook | local calculation driver exists; unsupported/shared/streamed cache paths differ | data.md:F05-F12 |
| external-links | done_bounded | listExternalLinks updateExternalLinks readExternalLinkUsage selectExternalLinkSource | limited authorized-file Update/Break/retarget shipped; complex formulas and range relay separate | data.md:D04-D05 |
| cross-workbook-pick | missing | listWorkbookTabs armWorkbookPick sendWorkbookPickSelection cancelWorkbookPick workbookPickArmed workbookPickSelected workbookPickCancelled | no active-workbook tab range relay; external argument picker explicitly throws | data.md:F03 |
| reveal-link | host_boundary | revealLinkSource | Web displays authorized file identity, no OS showItemInFolder | NATIVE_XLSX_EXTERNAL_LINKS_SOURCE_ACCEPTANCE_20261113.md |
| media-read | partial | readWorkbookMedia readLocalImage | bounded embedded ordinary/HF media and explicit uploads; external/MIME breadth not established | visuals.md:V24,V37,V41 |
| pivot-definition | done_bounded | readPivotDefinition | existing pivot read/create/edit path, advanced fields separately limited | data.md:P01-P11 |
| redactions | missing | readWorkbookRedactions | source gxRedactions and derived-cell withholding not transformed into local AI input | core.md, ai.md |
| query-metadata | done_bounded | readWorkbookQueries | read-only queries/connections metadata UI exists | data.md:D05-D08 |
| save | done_bounded | saveWorkbook | identity-bound immutable revision save/download replaces in-place desktop save | storage.md:S06 |
| connection-refresh | partial | listWorkbookConnections refreshWorkbookConnection | metadata exists but source supported web-table query fetch/refresh missing | data.md:D06 |
| edit-transfer | partial | saveEditsBegin saveEditsChunk saveEditsAbort | full operation JSON/budget exists, not ordered chunk transfer store | storage.md:S05 |
| recovery | partial | writeWorkbookRecovery recoveryPrompt recoveryPromptReply | local browser draft recovery, not independent recovered workbook bytes on disk | storage.md:S08 |
| rename | host_boundary | autoRenameWorkbook workbookRenamed | source filename auto-renaming/OS path notifications not equivalent to editor revision labels | storage.md, frontend/src/workbook-main.ts |
| dirty-close | partial | pendingEditsChanged closeSaveRequest closeSaveResult | local NativeDraft/beforeunload exists; source shell close-save request/receipt lifecycle differs | core.md, storage.md |
| print-export | host_boundary | exportPdf printWorkbook listPrinters | browser system print exists; direct PDF/device/copies/collate require host capability | visuals.md:V43 |
| csv-save | missing | exportCsv csvSaveConfirm | no native CSV display export/standalone CSV identity save-back | data.md:D03, storage.md:S11 |
| ai-create-document | host_boundary | createDocument | source creates standalone documents, local candidate authority does not | ai.md |
| shell-context | host_boundary | openExternal menuAction userDisplayName | Web navigation/context and authorized actor differ from shell APIs; no 1:1 IPC requirement | core.md, frontend/src/workbook-main.ts |
| ai-session | partial | aiGetSettings aiSetSettings aiSettingsChanged aiOpenModelSettings aiChat aiStream aiStreamCancel aiStreamChunk aiGskStatus aiGskLogin | Agno/local SSE/cancellation exist; source provider settings/login and persistent chat not all mirrored | ai.md |
| ai-images | host_boundary | aiImageSearch aiFetchImage aiGenerateImage | source external acquisition/generation not registered in workbook candidate host | ai.md |
| mcp-visible-grid | missing | mcpCommand mcpResult mcpReady | no source-equivalent authenticated XLSX visible-grid MCP execution bridge in inspected host | source apps/sheets/src/renderer/mcp-bridge.ts; frontend/src/workbook-main.ts |
| screen-capture | missing | captureScreenSources captureScreenSource | no workbook desktop-screen source capture picker in inspected native Web flow | visuals.md:V31; source desktop-api.ts |
| attachments | host_boundary | filesPick filesAdd filesAddPastedImage filesRead filesReadImage | source indexed chat attachment capabilities not registered by local workbook toolkit | ai.md |

Additional shell settings: source DesktopApi has 11-language/theme/document-theme/AutoSave/AI-panel preferences. Local ribbon labels are Chinese and its host owns settings separately; full per-language/OS/theme/IME parity is unverified. Standalone zero-byte XLSX open→blank workbook in source differs from native attachment _content rejecting empty bytes. Neither is a production incident claim.

No direct-source-equivalent API mapping was declared passing merely because a same-named callback exists. Generic document-control sessions or task_execution code are not proof of XLSX visible-grid MCP or durable workbook AI.
