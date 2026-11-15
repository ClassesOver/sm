# GenOffice account settings adaptation

Upstream: https://github.com/genspark-ai/genoffice
Commit: `f8c17004fb730df11f0f743164ffd8b4281bb38c`

Sources: `apps/shell/src/renderer/src/SettingsModal.tsx`, `settings.css`, and the account entry in `Home.tsx`.
The Docs application runs inside this shell. Its own `PreferencesDialog.tsx` only controls measurement units.

Retained: two-pane dialog JSX structure, SVG navigation icons and original CSS.
Adapted: personal-only navigation, Chinese labels, host callbacks in place of Electron IPC, keyboard focus containment/restoration, explicit save/retry/unsaved-change handling. Genspark login and administrator/provider configuration are not exposed by the personal component.
`upstream.css` is an unmodified reference; `dialog.css` contains scoped extracted rules for browser integration.

Copyright 2026 Mainfunc, Inc. Apache-2.0; see LICENSE and NOTICE.
