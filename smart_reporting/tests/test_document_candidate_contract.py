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
