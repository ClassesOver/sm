"""首次PPTX必须保留已登记的分析说明，并独立核对其当前知识支持。"""

import pytest

from smart_reporting.tests.test_initial_workbook_delivery import exercise_initial_workbook_delivery
from smart_reporting.tests.test_report_basis_persistence import auth_context as auth_context
from smart_reporting.tests.test_report_basis_persistence import basis_context as basis_context
from smart_reporting.tests.test_report_basis_persistence import document_context as document_context
from smart_reporting.tests.test_report_basis_persistence import index_context as index_context
from smart_reporting.tests.test_report_basis_persistence import receipt_snapshot as receipt_snapshot

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_first_pptx_registers_background_claim_and_keeps_historical_download_after_withdrawal(
    basis_context, document_context, receipt_snapshot, monkeypatch,
):
    await exercise_initial_workbook_delivery(basis_context, document_context, receipt_snapshot,
        monkeypatch, delivery_format='pptx')
