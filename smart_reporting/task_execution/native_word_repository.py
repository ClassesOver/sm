"""Narrow private Word persistence operations on the existing task repository.

No authentication, MCP endpoint, executor or provider is created by this mixin.
The caller is trusted editor infrastructure, not a model-facing tool. Returned private
values must never be inserted into generic task snapshots/log/result projections.
"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import exists, func, select, update

from .models import AttemptOutcome, AttemptState, TaskExecutionScope, TaskState
from .native_word_contracts import (
    MAX_NATIVE_WORD_RECEIPT_BYTES,
    NativeWordScope,
    NativeWordTaskInput,
    candidate_digest,
    canonical_bytes,
    canonical_digest,
    normalize_word_input,
    normalize_word_proposal,
    normalize_word_receipt,
    validate_word_finish_reference,
)


def _error(code: str):
    from .repository_impl import TaskExecutionRepositoryError

    return TaskExecutionRepositoryError(code, code)


class NativeWordTaskRepositoryMixin:
    async def create_native_word_task(self, scope: TaskExecutionScope, initial_instruction: str,
                                      word_input: NativeWordTaskInput | dict[str, Any]):
        try:
            parsed, payload, _digest = normalize_word_input(word_input)
        except ValueError:
            raise _error('native_word_input_invalid') from None
        if (parsed.binding.task_id != scope.external_run_id
                or parsed.binding.scope.user_id != scope.owner_user_id
                or parsed.binding.scope.thread_id != scope.thread_id
                or parsed.instruction_sha256 != hashlib.sha256(initial_instruction.encode()).hexdigest()):
            raise _error('native_word_binding_mismatch')
        # The initial task, attempt, instruction and private input are inserted in
        # the SAME existing creation transaction; there is no unbound runnable gap.
        return await self.create_task_with_initial_attempt(
            scope, initial_instruction, _native_word_input=payload)

    @staticmethod
    def _word_scope_conditions(tasks, scope: TaskExecutionScope):
        return (
            tasks.c.external_run_id == scope.external_run_id,
            tasks.c.owner_user_id == scope.owner_user_id,
            tasks.c.thread_id == scope.thread_id,
            tasks.c.sandbox_id == scope.sandbox_id,
            tasks.c.agent_id == scope.executor_id,
        )

    def _word_decode_input(self, value, *, scope, native_scope, expected_input_sha256):
        if value['native_word_input'] is None or value['native_word_input_sha256'] is None:
            raise _error('native_word_binding_missing')
        try:
            parsed, payload, digest = normalize_word_input(value['native_word_input'])
            principal_scope = NativeWordScope.model_validate(native_scope)
        except ValueError:
            raise _error('native_word_input_invalid') from None
        if (digest != value['native_word_input_sha256'] or digest != expected_input_sha256
                or parsed.binding.task_id != scope.external_run_id
                or parsed.binding.scope != principal_scope
                or parsed.binding.scope.user_id != scope.owner_user_id
                or parsed.binding.scope.thread_id != scope.thread_id
                or int(value['instruction_sequence']) != 1):
            raise _error('native_word_binding_mismatch')
        return parsed, payload, digest

    def _word_guard(self, *, scope, lease, internal_run_id, attempt_no,
                    expected_input_sha256, state_version, states, finishing_recovery=False):
        run_states = [AttemptState.FINISH_REQUESTED] if finishing_recovery else [AttemptState.RUNNING]
        run_conditions = [
            self.runs.c.external_run_id == scope.external_run_id,
            self.runs.c.internal_run_id == internal_run_id,
            self.runs.c.continuation_index == attempt_no,
            self.runs.c.status.in_(run_states),
        ]
        if not finishing_recovery:
            run_conditions.append(self.runs.c.lease_epoch == lease.epoch)
        return [
            *self._word_scope_conditions(self.tasks, scope),
            self.tasks.c.current_internal_run_id == internal_run_id,
            self.tasks.c.continuation_count == attempt_no,
            self.tasks.c.state_version == state_version,
            self.tasks.c.lease_owner == lease.owner,
            self.tasks.c.lease_epoch == lease.epoch,
            self.tasks.c.lease_expires_at > func.clock_timestamp(),
            self.tasks.c.deadline_at > func.clock_timestamp(),
            self.tasks.c.status.in_(states),
            self.tasks.c.instruction_sequence == 1,
            self.tasks.c.native_word_input_sha256 == expected_input_sha256,
            exists(select(self.runs.c.internal_run_id).where(*run_conditions)),
        ]

    async def _word_current(self, connection, *, scope, lease, internal_run_id, attempt_no,
                            expected_input_sha256, native_scope, recovery=False):
        row = (await connection.execute(select(self.tasks).where(
            *self._word_scope_conditions(self.tasks, scope)).with_for_update())).first()
        if row is None:
            raise _error('native_word_task_not_found')
        value = row._mapping
        # Fresh time AFTER acquiring the row lock. PG now() is transaction-start
        # time and is deliberately not used for this authorization boundary.
        current = (await connection.execute(select(func.clock_timestamp()))).scalar_one()
        states = [TaskState.ACTIVE]
        finishing = recovery and value['status'] == TaskState.FINISHING
        if finishing:
            states = [TaskState.FINISHING]
        if (value['status'] not in states or value['lease_owner'] != lease.owner
                or value['lease_epoch'] != lease.epoch
                or value['lease_expires_at'] is None or value['lease_expires_at'] <= current
                or value['deadline_at'] <= current
                or value['current_internal_run_id'] != internal_run_id
                or value['continuation_count'] != attempt_no):
            raise _error('native_word_execution_fenced')
        parsed, payload, digest = self._word_decode_input(value, scope=scope,
            native_scope=native_scope, expected_input_sha256=expected_input_sha256)
        instruction_hash = (await connection.execute(select(self.instructions.c.content_hash).where(
            self.instructions.c.external_run_id == scope.external_run_id,
            self.instructions.c.instruction_id == 'initial'))).scalar_one_or_none()
        if instruction_hash != parsed.instruction_sha256:
            raise _error('native_word_instruction_mismatch')
        guards = self._word_guard(scope=scope, lease=lease, internal_run_id=internal_run_id,
            attempt_no=attempt_no, expected_input_sha256=digest, state_version=value['state_version'],
            states=states, finishing_recovery=finishing)
        return value, parsed, payload, digest, guards

    async def _word_guarded_read(self, connection, guards):
        if (await connection.execute(select(self.tasks.c.external_run_id).where(*guards))).first() is None:
            raise _error('native_word_execution_fenced')

    async def read_native_word_input(self, **fence) -> dict[str, Any]:
        """Private current-executor read. Production caller must first authenticate its ticket."""
        await self.initialize()
        async with self.db.db_engine.begin() as connection:
            _value, _parsed, payload, _digest, guards = await self._word_current(connection, **fence)
            await self._word_guarded_read(connection, guards)
            return payload

    def _word_decode_receipt(self, value, parsed, digest):
        if value['native_word_candidate_receipt'] is None:
            if value['native_word_candidate_sha256'] is not None:
                raise _error('native_word_receipt_invalid')
            return None
        try:
            return normalize_word_receipt(value['native_word_candidate_receipt'], word_input=parsed,
                input_sha256=digest, candidate_sha256=value['native_word_candidate_sha256'])
        except ValueError:
            raise _error('native_word_receipt_invalid') from None

    async def commit_native_word_candidate(self, *, proposal: dict[str, Any],
                                           registered_proposal: dict[str, Any], **fence) -> dict[str, Any]:
        """One immutable receipt, atomically fenced; does not accept/save a document.

        registered_proposal must come from the trusted task's NativeWordAITools,
        never from a second model-supplied field. This repository is not itself an
        authenticated RPC surface and does not claim to prove tool read coverage.
        """
        # Size/equality checks happen before acquiring a contested task row lock.
        if (len(canonical_bytes(proposal)) > MAX_NATIVE_WORD_RECEIPT_BYTES
                or len(canonical_bytes(registered_proposal)) > MAX_NATIVE_WORD_RECEIPT_BYTES):
            raise _error('native_word_proposal_too_large')
        if canonical_digest(proposal) != canonical_digest(registered_proposal):
            raise _error('native_word_registered_proposal_mismatch')
        await self.initialize()
        async with self.db.db_engine.begin() as connection:
            value, parsed, _payload, digest, guards = await self._word_current(connection, **fence)
            try:
                normalized = normalize_word_proposal(parsed, proposal)
            except ValueError:
                raise _error('native_word_candidate_invalid') from None
            semantic_digest = candidate_digest(digest, normalized)
            previous = self._word_decode_receipt(value, parsed, digest)
            if previous is not None:
                # Current lease/attempt is checked BEFORE this idempotent return.
                if semantic_digest != previous['candidateSha256']:
                    raise _error('native_word_candidate_conflict')
                await self._word_guarded_read(connection, guards)
                return previous
            committed_at = (await connection.execute(select(func.clock_timestamp()))).scalar_one()
            receipt = {'version': 1, 'taskId': parsed.binding.task_id,
                'inputSha256': digest, 'candidateSha256': semantic_digest, 'proposal': normalized,
                'originCommit': {'internalRunId': fence['internal_run_id'], 'attemptNo': fence['attempt_no'],
                    'leaseOwner': fence['lease'].owner, 'leaseEpoch': fence['lease'].epoch,
                    'committedAt': committed_at.isoformat().replace('+00:00', 'Z')}}
            receipt['receiptSha256'] = canonical_digest(receipt)
            receipt = normalize_word_receipt(receipt, word_input=parsed, input_sha256=digest,
                                               candidate_sha256=semantic_digest)
            result = await connection.execute(update(self.tasks).where(*guards,
                self.tasks.c.native_word_candidate_receipt.is_(None),
                self.tasks.c.native_word_candidate_sha256.is_(None)).values(
                    native_word_candidate_receipt=receipt, native_word_candidate_sha256=semantic_digest,
                    state_version=self.tasks.c.state_version + 1, updated_at=func.clock_timestamp()))
            if result.rowcount != 1:
                raise _error('native_word_execution_fenced')
            return receipt

    async def recover_native_word_candidate(self, **fence) -> dict[str, Any] | None:
        """Fresh claim recovers original receipt; never compare origin attempt to current.

        In FINISHING, the claimed task epoch is current but the FINISH_REQUESTED run
        epoch may be historical. Only this read path permits that, never commit.
        """
        await self.initialize()
        async with self.db.db_engine.begin() as connection:
            value, parsed, _payload, digest, guards = await self._word_current(connection, recovery=True, **fence)
            receipt = self._word_decode_receipt(value, parsed, digest)
            if value['status'] == TaskState.FINISHING:
                if receipt is None:
                    raise _error('native_word_receipt_missing')
                self._word_finish_reference(value, receipt)
            await self._word_guarded_read(connection, guards)
            return receipt

    @staticmethod
    def _word_finish_reference(value, receipt):
        try:
            validate_word_finish_reference(value['finish_receipt'], receipt)
        except ValueError:
            raise _error('native_word_finish_reference_mismatch') from None

    async def get_completed_native_word_candidate(self, scope: TaskExecutionScope, *,
            expected_input_sha256: str, native_scope: dict[str, Any]) -> dict[str, Any]:
        """Private completed result read, NOT editor grant verification or acceptance.

        The editor must separately revalidate a CURRENT grant/context/source/draft.
        No old execution lease is required; completed-task generic cancel is a no-op.
        """
        await self.initialize()
        async with self.db.db_engine.connect() as connection:
            row = (await connection.execute(select(self.tasks).where(
                *self._word_scope_conditions(self.tasks, scope),
                self.tasks.c.status == TaskState.COMPLETED))).first()
            if row is None:
                raise _error('native_word_not_completed')
            value = row._mapping
            parsed, _payload, digest = self._word_decode_input(value, scope=scope,
                native_scope=native_scope, expected_input_sha256=expected_input_sha256)
            receipt = self._word_decode_receipt(value, parsed, digest)
            if receipt is None:
                raise _error('native_word_receipt_missing')
            self._word_finish_reference(value, receipt)
            completed_run = (await connection.execute(select(self.runs.c.internal_run_id).where(
                self.runs.c.external_run_id == scope.external_run_id,
                self.runs.c.internal_run_id == value['current_internal_run_id'],
                self.runs.c.continuation_index == value['continuation_count'],
                self.runs.c.status == AttemptState.CLOSED,
                self.runs.c.outcome == AttemptOutcome.FINISH_ACCEPTED))).first()
            if completed_run is None:
                raise _error('native_word_completion_unproven')
            return receipt
