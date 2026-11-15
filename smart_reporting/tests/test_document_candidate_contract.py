import pytest

from smart_reporting.document_candidate_contract import (
    DocumentAdapterRegistry,
    DocumentCandidateRequest,
    DocumentFormat,
    DocumentScope,
)


def scope(fmt=DocumentFormat.DOCX, digest="a" * 64):
    return DocumentScope("channel", "grant", "document", "1", digest, fmt)


@pytest.mark.parametrize("fmt", list(DocumentFormat))
def test_document_formats_share_authorized_scope(fmt):
    request = DocumentCandidateRequest(
        scope(fmt), "request_1", "Revise selected content", ({"objectId": "one"},)
    )
    assert request.scope.format == fmt
    assert request.scope.grant == "grant"


@pytest.mark.parametrize("digest", ["", "a" * 63, "z" * 64, "A" * 64])
def test_invalid_source_identity_rejected(digest):
    with pytest.raises(ValueError, match="document_source_digest_invalid"):
        scope(digest=digest)


@pytest.mark.parametrize("request_id", ["", "bad id", "x" * 129, "含中文"])
def test_invalid_request_id_rejected(request_id):
    with pytest.raises(ValueError, match="document_request_id_invalid"):
        DocumentCandidateRequest(scope(), request_id, "Edit", ({"objectId": "one"},))


def test_empty_selection_rejected():
    with pytest.raises(ValueError, match="document_selection_invalid"):
        DocumentCandidateRequest(scope(), "id", "Edit", ())


def test_registry_fails_closed_and_rejects_duplicates():
    registry = DocumentAdapterRegistry()
    with pytest.raises(ValueError, match="document_adapter_unavailable"):
        registry.require(DocumentFormat.XLSX)

    class Adapter:
        format = DocumentFormat.DOCX

    adapter = Adapter()
    registry.register(adapter)
    assert registry.require(DocumentFormat.DOCX) is adapter
    with pytest.raises(ValueError, match="document_adapter_already_registered"):
        registry.register(adapter)


def test_selection_snapshot_is_independent_of_caller_mutations():
    target = {"cell": "A1", "metadata": {"sheet": "Sheet1"}}
    request = DocumentCandidateRequest(scope(DocumentFormat.XLSX), "id", "Edit", (target,))
    target["cell"] = "Z99"
    target["metadata"]["sheet"] = "Other"
    assert request.selection == ({"cell": "A1", "metadata": {"sheet": "Sheet1"}},)


@pytest.mark.parametrize("selection", [(None,), ({},), ("A1",)])
def test_malformed_selection_rejected(selection):
    with pytest.raises(ValueError, match="document_selection_invalid"):
        DocumentCandidateRequest(scope(), "id", "Edit", selection)


@pytest.mark.parametrize("selection", [
    ({"value": float("nan")},),
    ({"value": float("inf")},),
    ({"value": object()},),
    ({"value": {"nested": {1, 2}}},),
    ({"value": "x" * 65537},),
])
def test_document_selection_rejects_non_json_and_oversized_payloads(selection):
    with pytest.raises(ValueError, match="document_selection_invalid"):
        DocumentCandidateRequest(scope(), "id", "Edit", selection)


@pytest.mark.parametrize("kwargs,error", [
    ({"channel": None}, "document_scope_incomplete"),
    ({"grant": "  "}, "document_scope_incomplete"),
    ({"document_id": 42}, "document_scope_incomplete"),
    ({"revision": None}, "document_scope_incomplete"),
    ({"source_sha256": None}, "document_source_digest_invalid"),
    ({"format": "unknown"}, "document_format_invalid"),
])
def test_malformed_document_scope_fails_with_explicit_validation(kwargs, error):
    values = dict(channel="channel", grant="grant", document_id="document",
                  revision="1", source_sha256="a" * 64, format=DocumentFormat.DOCX)
    values.update(kwargs)
    with pytest.raises(ValueError, match=error):
        DocumentScope(**values)


@pytest.mark.parametrize("kwargs,error", [
    ({"request_id": None}, "document_request_id_invalid"),
    ({"instruction": None}, "document_instruction_invalid"),
    ({"selection": None}, "document_selection_invalid"),
    ({"selection": "A1"}, "document_selection_invalid"),
])
def test_malformed_candidate_request_types_fail_closed(kwargs, error):
    values = dict(scope=scope(), request_id="one", instruction="Edit",
                  selection=({"objectId": "one"},))
    values.update(kwargs)
    with pytest.raises(ValueError, match=error):
        DocumentCandidateRequest(**values)
