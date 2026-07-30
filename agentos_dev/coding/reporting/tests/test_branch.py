import hashlib
from types import SimpleNamespace

import pytest
from ag_ui.core import EventType
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

from agentos_dev.branch import BranchSpec, prepare_branch, run_branch
from agentos_dev.coding.reporting.data_sources import REPORT_DATASET_HANDLES_STATE_KEY
from agentos_dev.coding.reporting.workspace import REPORT_JOBS_STATE_KEY


def source_session():
    return AgentSession(
        session_id="source-thread",
        agent_id="odoo-assistant",
        user_id="owner",
        runs=[
            RunOutput(
                run_id=f"run-{index}",
                session_id="source-thread",
                agent_id="odoo-assistant",
                status=RunStatus.completed,
                content=f"answer-{index}",
            )
            for index in range(1, 4)
        ],
    )


class FakeAgent:
    def __init__(self):
        self.source = source_session()
        self.saved = []
        self.deleted = []
        self.db = object()

    async def aget_session(self, session_id=None, user_id=None):
        if session_id == "source-thread" and user_id == "owner":
            return self.source
        return None

    async def asave_session(self, session):
        self.saved.append(session)

    async def adelete_session(self, session_id, user_id=None):
        self.deleted.append((session_id, user_id))


class FakeWorkspace:
    def __init__(self):
        self.copied = []
        self.destroyed = []

    async def acopy_branch(self, source, target):
        self.copied.append((source, target))
        return {"files": 2, "bytes": 10}

    async def adestroy(self, thread):
        self.destroyed.append(thread)


def run_input():
    return SimpleNamespace(
        thread_id="target-thread",
        state={"protocol": "agui.odoo.v2", "host": {}, "agent": {}},
        context=[],
        tools=[],
    )


class DatasetBranchWorkspace(FakeWorkspace):
    def __init__(self, *, copied_sha256="a" * 64):
        super().__init__()
        self.copied_sha256 = copied_sha256
        self.files = {
            ("source-thread", "收入.csv"): {"size": 12, "sha256": "a" * 64},
        }

    async def acopy_branch(self, source, target):
        result = await super().acopy_branch(source, target)
        source_file = self.files[(source, "收入.csv")]
        self.files[(target, "收入.csv")] = {
            **source_file,
            "sha256": self.copied_sha256,
        }
        return result

    async def astat(self, thread, path):
        value = self.files[(thread, path)]
        return {"path": path, "type": "file", **value}

    async def ahash_file(self, thread, path):
        return {"path": path, **self.files[(thread, path)]}


def report_dataset_session_data():
    dataset_id = "dataset-branch"
    return {
        "session_state": {
            REPORT_DATASET_HANDLES_STATE_KEY: {
                dataset_id: {
                    "datasetId": dataset_id,
                    "sourceId": "operations",
                    "sourceType": "starrocks_materialized",
                    "path": "收入.csv",
                    "format": "csv",
                    "schema": None,
                    "rowCount": 1,
                    "size": 12,
                    "sha256": "a" * 64,
                    "provenance": {
                        "requirementId": "income",
                        "sqlHash": "b" * 64,
                    },
                    "_threadBinding": hashlib.sha256(b"source-thread").hexdigest(),
                }
            },
            REPORT_JOBS_STATE_KEY: {"source-job": {"validation": {"ok": True}}},
            "unrelated_server_state": {"mustNotCopy": True},
        }
    }


@pytest.mark.anyio
async def test_branch_revalidates_and_rebinds_report_dataset_handles():
    agent = FakeAgent()
    agent.id = "report-agent"
    agent.source.session_data = report_dataset_session_data()
    workspace = DatasetBranchWorkspace()

    await prepare_branch(
        agent,
        workspace,
        BranchSpec("source-thread", "run-1", "answer-1"),
        "target-thread",
        "owner",
    )

    target_state = agent.saved[0].session_data["session_state"]
    assert agent.saved[0].agent_id == "report-agent"
    assert set(target_state) == {REPORT_DATASET_HANDLES_STATE_KEY}
    rebound = target_state[REPORT_DATASET_HANDLES_STATE_KEY]["dataset-branch"]
    assert rebound["datasetId"] == "dataset-branch"
    assert rebound["sha256"] == "a" * 64
    assert rebound["_threadBinding"] == hashlib.sha256(b"target-thread").hexdigest()
    source_handle = agent.source.session_data["session_state"][REPORT_DATASET_HANDLES_STATE_KEY][
        "dataset-branch"
    ]
    assert source_handle["_threadBinding"] == hashlib.sha256(b"source-thread").hexdigest()


@pytest.mark.anyio
async def test_branch_rejects_changed_copied_dataset_with_stable_code():
    agent = FakeAgent()
    agent.source.session_data = report_dataset_session_data()
    workspace = DatasetBranchWorkspace(copied_sha256="b" * 64)

    events = [
        event
        async for event in run_branch(
            agent,
            workspace,
            run_input(),
            BranchSpec("source-thread", "run-1", "answer-1"),
            "owner",
        )
    ]

    assert len(events) == 1
    assert events[0].type == EventType.RUN_ERROR
    assert events[0].code == "stale_dataset"
    assert events[0].message == "无法基于所选消息创建分支。"
    assert agent.deleted == [("target-thread", "owner")]
    assert workspace.destroyed == ["target-thread"]
