from dataclasses import replace
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.contract import ModelColumn, ModelTable, schema_hash
from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable
from smart_reporting.reporting.data_source.profiling import _catalog_scope
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.type_normalization import normalize_data_type


def test_normalize_data_type_removes_whitespace_and_ignores_case():
    assert normalize_data_type(" decimal ( 10, 2 ) ") == "DECIMAL(10,2)"


def test_schema_hash_ignores_type_spelling_but_preserves_precision():
    table = ModelTable(
        sourceId="source", database="reporting", name="income",
        columns=(ModelColumn(name="amount", dataType="DECIMAL(10,2)", nullable=True),),
    )
    spelled = table.model_copy(update={
        "columns": (table.columns[0].model_copy(update={"data_type": " decimal ( 10, 2 ) "}),),
    })
    changed = table.model_copy(update={
        "columns": (table.columns[0].model_copy(update={"data_type": "DECIMAL(12,2)"}),),
    })
    assert schema_hash((table,)) == schema_hash((spelled,))
    assert schema_hash((table,)) != schema_hash((changed,))


@pytest.mark.parametrize("current_type", [" decimal ( 10, 2 ) ", "DECIMAL(12,2)"])
def test_catalog_scope_ignores_type_spelling_but_rejects_precision_drift(current_type):
    table = CatalogTable(
        source_id="source", database="reporting", name="income",
        columns=(CatalogColumn(name="amount", data_type="DECIMAL(10,2)", nullable=True),),
    )
    current = replace(table, columns=(replace(table.columns[0], data_type=current_type),))
    adapter = SimpleNamespace(config=SimpleNamespace(id="source", database="reporting"))
    if current_type == "DECIMAL(12,2)":
        with pytest.raises(ReportingError, match="report_catalog_drift"):
            _catalog_scope(adapter, (current,), (table,))
    else:
        assert _catalog_scope(adapter, (current,), (table,)) == (current,)
