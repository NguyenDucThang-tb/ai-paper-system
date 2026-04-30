from app.models.document import Document
from app.models.document_summary import DocumentSummary


def test_list_documents_returns_owned_only(client, db_session, default_user):
    own_doc = Document(
        filename="own.txt",
        file_type="text/plain",
        user_id=default_user.id,
        status="uploaded",
        raw_text="hello",
        is_deleted=False,
    )
    other_doc = Document(
        filename="other.txt",
        file_type="text/plain",
        user_id=999,
        status="uploaded",
        raw_text="world",
        is_deleted=False,
    )
    db_session.add_all([own_doc, other_doc])
    db_session.commit()

    res = client.get("/api/v1/documents")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["filename"] == "own.txt"


def test_update_and_get_document_metadata(client, db_session, default_user):
    doc = Document(
        filename="meta.pdf",
        file_type="application/pdf",
        user_id=default_user.id,
        status="uploaded",
        raw_text="raw text",
        is_deleted=False,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    patch_res = client.patch(
        f"/api/v1/documents/{doc.id}/metadata",
        json={
            "title": "AI Paper",
            "authors": ["Alice", "Bob"],
            "publication_year": 2024,
            "topics": ["NLP"],
        },
    )
    assert patch_res.status_code == 200
    patch_data = patch_res.json()
    assert patch_data["title"] == "AI Paper"
    assert patch_data["authors"] == ["Alice", "Bob"]

    get_res = client.get(f"/api/v1/documents/{doc.id}/metadata")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["publication_year"] == 2024
    assert get_data["topics"] == ["NLP"]


def test_request_and_get_summary_contract(client, db_session, default_user):
    doc = Document(
        filename="summary.docx",
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        user_id=default_user.id,
        status="uploaded",
        raw_text="content",
        is_deleted=False,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    req_res = client.post(
        f"/api/v1/cms/documents/{doc.id}/summary/request",
        json={"level": "medium"},
    )
    assert req_res.status_code == 200
    assert req_res.json()["status"] == "accepted"

    db_session.add(
        DocumentSummary(
            document_id=doc.id,
            summary_short="short",
            summary_medium="medium",
            summary_long="long",
        )
    )
    db_session.commit()

    get_res = client.get(f"/api/v1/cms/documents/{doc.id}/summary")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["document_id"] == doc.id
    assert get_data["summary_medium"] == "medium"
