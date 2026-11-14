"""补丁回执：失租约后只有真实回读为after才可报告成功。"""

import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.task_execution.repository import TaskExecutionRepositoryError
from smart_reporting.task_execution.tests.test_internal_harness_patch_faults import (
    patch_runtime as patch_runtime,
)


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['create', 'overwrite', 'replace'])
@pytest.mark.parametrize('readback', ['after', 'before'])
async def test_patch_success_requires_confirmed_after_state(patch_runtime, mode, readback):
    runtime = patch_runtime
    error = TaskExecutionRepositoryError('task_lease_lost', 'synthetic postwrite takeover')
    runtime.repository.validate_execution_fence.side_effect = [None, error]

    async def execution(_execution_id):
        reservation = runtime.repository.reserve_execution.await_args.kwargs
        return SimpleNamespace(thread_id='thread', operation_receipt=reservation['operation_receipt'])

    runtime.repository.get_execution.side_effect = execution
    # create的before态为不存在，已由PR #230的missing回归覆盖。
    digest = 'new' if readback == 'after' else 'same'
    runtime.workspace.ahash_file.return_value = {'sha256': hashlib.sha256(digest.encode()).hexdigest()}

    async def patch():
        return await runtime.kernel.patch(
            mode, 'result.txt', 'same' if mode == 'replace' else None,
            'new' if mode == 'replace' else None, False, None, None,
            content=None if mode == 'replace' else 'new',
            expected_sha256=hashlib.sha256(b'same').hexdigest() if mode == 'overwrite' else None,
            _scope=runtime.scope,
        )

    if readback == 'before':
        with pytest.raises(TaskExecutionRepositoryError) as captured:
            await patch()
        assert captured.value is error
        assert all(call.kwargs['status'] != 'completed'
                   for call in runtime.repository.update_execution.await_args_list)
    else:
        result = await patch()
        assert result['ok'] is True
        update = runtime.repository.update_execution.await_args.kwargs
        assert update['status'] == 'completed' and update['exit_code'] == 0
