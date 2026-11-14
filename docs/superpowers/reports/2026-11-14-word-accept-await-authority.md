# Word accept await authority checks

Base: PR #240 c6c61531317a8ac985791da35bff4bafa3c6cb38, tree 9723a974b1a57d5b1e10c47bbb6379ef96a338e7. Remote code remained 2ed02513b5fbc3ae1fadc98be38df0661fe649bc before execution. Production files are unchanged.

Added six synthetic integration cases: preview and completed-receipt reads each pause after the real operation; while accept waits, the registered session naturally expires (future deadline followed by real wall time), is removed from the actual fixture session repository, or the actual temporary DOCX source is replaced. The session repository is the existing in-memory registration fixture; task persistence and receipts use disposable PostgreSQL 18. Actual HTTP, authenticated FastMCP and Node DOCX inspect/patch execute with a synthetic transport, without Codex/provider calls.

Each case requires the domain rejection code, accepted=False, no revision 2 and no accept-side source write. The source-change cases compare the external replacement bytes and restore the original during cleanup.

Evidence: /workspace/word-accept-race. Exact commands, redacted synthetic env, source hashes, JUnit, full stdout/stderr, exit codes, PostgreSQL version/inspect and cleanup are retained there.

- Round 1: the six-case file, exit 1, 4 passed / 2 failed / 1 warning, 176.00 seconds. Expiry and revocation passed. Both source cases failed in test injection and cleanup with WorkspacePathConflict because overwrite=True was omitted. These are test interface failures, NOT business RED.
- Round 2: only `-k source_changed`, exit 0, 2 passed / 4 deselected / 1 warning. Corrected the test's explicit overwrite calls; production unchanged. Six unique cases cumulatively passed, not a single six-pass run and not a RED-to-GREEN production repair.
- Ruff for the new test and diff-check passed. No full 106-case or project suite repeated.

Both rounds report visions/utils/monkeypatches/imghdr_patch.py:2 DeprecationWarning: 'imghdr' is deprecated and slated for removal in Python 3.13. Full logs also retain Agno duplicate execute registration warnings, the fresh database's management_configuration_schema_missing warning, and native_refresh_capability_unavailable ReportingError warnings.

Both fresh containers and their captured anonymous volumes were deleted and verified absent; temporary HOME/DOCKER_CONFIG and runtime links were removed. No push, PR update, merge or deployment.

No production defect was demonstrated. This establishes re-observation across the two tested waits, not cross-service linearizable revocation. A change after the final observed authority check remains outside this bounded claim. Real Codex/Agno worker functionality remains unverified.
