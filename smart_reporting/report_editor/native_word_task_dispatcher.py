"""Optional Word task adapter on existing NativeAIService job/lifecycle paths.

No runner loop, listener, provider factory or default application wiring. Transport
is a single trusted run adapter; actual Codex use requires independently verified
runtime isolation. Only the short-lived Word ticket may reach that runtime.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..reporting.models import ReportingError
from ..task_execution.models import AttemptOutcome, TaskExecutionScope, TaskState
from ..task_execution.native_word_contracts import (
    NativeWordTaskInput,
    canonical_bytes,
    canonical_digest,
    word_finish_reference,
)
from ..task_execution.repository import TaskExecutionRepositoryError
from ..task_execution.session import TaskSession
from .native_word_ai import NativeWordAIProposal
from .native_word_task_builder import NativeWordTaskInputBuilder, _session_identity
from .native_word_task_mcp import WordTaskMcpBridge, WordTaskTicketCodec


def _invalid(code='native_word_task_invalid'):
    return ReportingError(code, 'Word 任务不可用或授权已变化。')


@dataclass(frozen=True)
class WordTaskReference:
    scope: TaskExecutionScope
    input_sha256: str
    word_input: NativeWordTaskInput = field(repr=False)


class WordTaskDispatcher:
    def __init__(self, repository, grants, editor, *, scope_factory, secret,
                 transport=None, enabled=False):
        self.repository, self.grants, self.editor = repository, grants, editor
        self.scope_factory, self.transport, self.enabled = scope_factory, transport, enabled
        self.codec = WordTaskTicketCodec(secret)
        self.builder = NativeWordTaskInputBuilder(grants, editor)

    def require_available(self):
        if not self.enabled or self.transport is None or self.scope_factory is None:
            raise _invalid('native_word_task_unavailable')

    async def prepare(self, *, context, session_reference, instruction, expected_sha256,
                      operations, selection, request_id):
        self.require_available()
        if not session_reference:
            raise _invalid()
        task_id = 'word-' + canonical_digest({'context': context.digest(), 'request': request_id})
        scope = self.scope_factory(context, task_id)
        if not isinstance(scope, TaskExecutionScope) or scope.external_run_id != task_id:
            raise _invalid()
        try:
            value = await self.builder.build(scope=scope, server_session_reference=session_reference,
                instruction=instruction, expected_sha256=expected_sha256, operations=operations, selection=selection)
        except ValueError as error:
            if type(error) is not ValueError or error.args != ('native_word_builder_invalid',):
                raise
            raise ReportingError('native_ai_selection_invalid',
                '当前 Word 任务输入不受支持或授权已变化，请重新选择。') from None
        try:
            await self.repository.create_native_word_task(scope, instruction, value)
        except TaskExecutionRepositoryError as error:
            if error.code in {'native_word_input_conflict', 'task_initial_instruction_conflict'}:
                raise _invalid('native_ai_snapshot_changed') from None
            raise
        return WordTaskReference(scope, canonical_digest(value.model_dump(mode='json', by_alias=True)), value)

    @staticmethod
    def _fence(ref, task_session, task):
        return dict(scope=ref.scope, lease=task_session.lease, internal_run_id=task.current_internal_run_id,
            attempt_no=task.current_attempt_no, expected_input_sha256=ref.input_sha256,
            native_scope=ref.word_input.binding.scope.model_dump(mode='json', by_alias=True))

    async def _current_editor(self, ref, session_reference, base=None):
        from .native_ai import NativeAIService

        session = await self.grants.lookup_registered_session(session_reference)
        identity = _session_identity(session)
        context = await self.editor.context_for_session(session)
        binding = ref.word_input.binding
        if (context.format != 'docx' or context.scope.model_dump(mode='json', by_alias=True)
                != binding.scope.model_dump(mode='json', by_alias=True)
                or context.document_id != binding.document_id or context.revision != binding.revision
                or context.digest() != binding.context_sha256
                or context.source_file.sha256 != binding.source_sha256
                or (base is not None and NativeAIService._snapshot(context, base) != binding.snapshot_sha256)):
            raise _invalid()
        await self.editor.read_file(context)
        # Re-observe registry after file IO, then check expiry after every await.
        last = await self.grants.lookup_registered_session(session_reference)
        final_context = await self.editor.context_for_session(last)
        if final_context.digest() != binding.context_sha256:
            raise _invalid()
        last = await self.grants.lookup_registered_session(session_reference)
        if (_session_identity(last) != identity or last.expires_at <= datetime.now(UTC)):
            raise _invalid()
        return context

    async def completed(self, ref, *, session_reference, base):
        # Private snapshot before suspension; never accept a raw model proposal here.
        base = json.loads(canonical_bytes(base))
        await self._current_editor(ref, session_reference, base)
        receipt = await self.repository.get_completed_native_word_candidate(ref.scope,
            expected_input_sha256=ref.input_sha256,
            native_scope=ref.word_input.binding.scope.model_dump(mode='json', by_alias=True))
        await self._current_editor(ref, session_reference, base)
        return NativeWordAIProposal.model_validate(receipt['proposal'])

    async def execute(self, ref):
        self.require_available()
        task = await self.repository.get_task_snapshot(ref.scope.external_run_id)
        if task is None or task.scope != ref.scope:
            raise _invalid()
        if task.state is TaskState.COMPLETED:
            return await self._completed_proposal(ref)
        async with TaskSession(self.repository, ref.scope) as task_session:
            return await self._execute_claim(ref, task_session)

    async def _completed_proposal(self, ref):
        receipt = await self.repository.get_completed_native_word_candidate(ref.scope,
            expected_input_sha256=ref.input_sha256,
            native_scope=ref.word_input.binding.scope.model_dump(mode='json', by_alias=True))
        return NativeWordAIProposal.model_validate(receipt['proposal'])

    async def _close_failed_claim(self, ref, task_session, error):
        # Executing code may only close its own still-live claim. Unlike an
        # authenticated editor's explicit cancel, local timeout/cancellation must
        # never cancel a newer owner. DB failures mean unknown, not guessed failure.
        try:
            current = await self.repository.get_task_snapshot(ref.scope.external_run_id)
            if (current is None or current.scope != ref.scope or current.state is not TaskState.ACTIVE
                    or current.lease_owner != task_session.lease.owner
                    or current.lease_epoch != task_session.lease.epoch):
                return
            receipt = await self.repository.recover_native_word_candidate(
                **self._fence(ref, task_session, current))
            if receipt is not None:
                return  # committed candidate/uncertain acknowledgement: preserve recovery
            local_cancel = isinstance(error, asyncio.CancelledError)
            owner = asyncio.current_task()
            local_cancel = local_cancel or (owner is not None and owner.cancelling())
            await self.repository.close_and_decide(ref.scope.external_run_id, task_session.lease,
                current.state_version, outcome=AttemptOutcome.CANCELLED if local_cancel else AttemptOutcome.ERROR,
                agno_status='cancelled' if local_cancel else 'error',
                error='word_task_cancelled' if local_cancel else 'word_task_transport_failed', create_next=False)
        except Exception:
            # Failed/ambiguous fence or database operation must not mask the actual
            # failure, retry the model, or acquire authority via scope-only cancel.
            return

    async def _execute_claim(self, ref, task_session):
        task_id = ref.scope.external_run_id
        session_reference = ref.word_input.binding.server_session_reference
        bridge = None
        try:
            task = await self.repository.get_task_snapshot(task_id)
            if task.state is TaskState.NEW:
                task, _ = await self.repository.open_initial(task_id, task_session.lease, task.state_version)
            elif task.state in {TaskState.ACTIVE, TaskState.SUSPENDED}:
                task, _ = await self.repository.resume_current(task_id, task_session.lease, task.state_version)
            elif task.state is not TaskState.FINISHING:
                raise _invalid()
            fence = self._fence(ref, task_session, task)
            receipt = await self.repository.recover_native_word_candidate(**fence)
            if receipt is None:
                await self._current_editor(ref, session_reference)
                session = await self.grants.lookup_registered_session(session_reference)
                principal = {'taskId': task_id,
                    'scope': ref.word_input.binding.scope.model_dump(mode='json', by_alias=True),
                    'inputSha256': ref.input_sha256, 'owner': task_session.lease.owner,
                    'epoch': task_session.lease.epoch, 'runId': task.current_internal_run_id,
                    'attempt': task.current_attempt_no, 'stateVersion': task.state_version}
                expires_at = min(datetime.now(UTC).timestamp() + 60,
                                 session.expires_at.timestamp(), task.deadline_at.timestamp())
                ticket = self.codec.issue(principal, expires_at=expires_at)
                async def authorize():
                    task_session.assert_alive()
                    current = await self.repository.get_task_snapshot(task_id)
                    if current is None or current.state_version != principal['stateVersion']:
                        raise _invalid()
                    await self.repository.read_native_word_input(**self._fence(ref, task_session, current))
                    await self._current_editor(ref, session_reference)
                    # Re-read the durable fence after all slower editor/source IO;
                    # TaskSession.assert_alive alone is only a local lease snapshot.
                    await self.repository.read_native_word_input(**self._fence(ref, task_session, current))
                    task_session.assert_alive()
                    return principal
                selected = ref.word_input.model_dump(mode='json', by_alias=True)['selectedParagraphs']
                bridge = WordTaskMcpBridge(selected=selected, principal=principal, authorize=authorize,
                    codec=self.codec, enabled=True)
                # Transport owns exactly one existing harness/Agno run. It receives no
                # parent env, DB credentials, source path or signing secret.
                instruction = await self.repository.attempt_instruction(task_id, task.current_attempt_no)
                if hashlib.sha256(instruction.encode()).hexdigest() != ref.word_input.instruction_sha256:
                    raise _invalid()
                final = await self.transport.run(server=bridge.server, ticket=ticket,
                    task_id=task_id, instruction=instruction)
                parsed = await bridge.reconcile(final, ticket=ticket)
                task_session.assert_alive()
                await self._current_editor(ref, session_reference)
                receipt = await self.repository.commit_native_word_candidate(
                    proposal=parsed.model_dump(mode='json'),
                    registered_proposal=bridge.registered_proposal,
                    **self._fence(ref, task_session, task))
            task = await self.repository.get_task_snapshot(task_id)
            if task.state is not TaskState.FINISHING:
                task = await self.repository.request_finish(task_id, task_session.lease,
                    task.state_version, word_finish_reference(receipt),
                    result_text='Word candidate receipt registered; not accepted or saved.', retained_execution_ids=[])
            await self.repository.finalize_finish(task_id, task_session.lease, task.state_version,
                agno_status='receipt-recovered' if bridge is None else 'completed')

            return await self._completed_proposal(ref)
        except BaseException as error:
            if bridge is not None:
                bridge.cancel()
            await self._close_failed_claim(ref, task_session, error)
            if not isinstance(error, asyncio.CancelledError):
                owner = asyncio.current_task()
                if owner is not None and owner.cancelling():
                    raise asyncio.CancelledError() from None
            raise

    async def cancel(self, ref):
        return await self.repository.cancel_and_reject(ref.scope)
