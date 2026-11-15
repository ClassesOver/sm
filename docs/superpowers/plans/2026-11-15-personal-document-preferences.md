# Personal document preferences and existing source management

User-authorized scope: reuse original data-source management; relocate its preferences to personal settings with per-user persistence; label Skill 技能; no export settings or Markdown preferences. Keep admin global provider/source/user authority.

Implementation choices: link admin source configuration to existing /management/sources and retain Office workspace grants as a separate admin action. Preserve existing management authentication; do not silently grant global admin sessions. Remove old management preference navigation; old UI route leads to Office personal preferences. Reuse existing field widgets and validation primitives, not global preference draft/publish APIs. Store document preferences in existing Office settings table under a separate company/user owner key with CAS, independent of theme/skills. Strict four-format schemas exclude export and MD fields. No automatic rewrite of existing documents; authorized native AI receives preferences as lower-priority formatting defaults and still previews/proposes edits through its existing authority.

Tasks:
1. Regression tests for per-user/company isolation, CAS/CSRF, schema exclusions, and native agent preference context.
2. Strict preference models/storage/API; attach saved defaults to native per-run agents.
3. Reuse field controls in personal preferences; retain unsaved edits, stale identity guard and keyboard/dialog behavior. Rename visible Skill labels.
4. Existing source management link, distinct workspace authorization action, legacy preference navigation redirect. No MD/export controls.
5. Focused backend/frontend tests, type/build validation, independent review, real browser screenshot of light-mode preferences if environment permits. Sync existing PR245.

Visual refinement requested during verification: reduce density; two-column form layout on desktop, single column on narrow screens; document formats use top Tab controls with arrow/Home/End navigation; secondary categories use compact tabs. Collapse typography/row-column details, retain long header/footer fields across both columns, keep save controls outside the scrolling content.
