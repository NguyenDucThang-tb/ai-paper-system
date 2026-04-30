from app.models.document import Document


def test_internal_chunks_requires_token(client, db_session, default_user):
    doc = Document(
        filename="internal.txt",
        file_type="text/plain",
        user_id=default_user.id,
        status="uploaded",
        raw_text="internal content",
        is_deleted=False,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    no_token_res = client.post(
        f"/api/v1/internal/chunks/?document_id={doc.id}",
        json=[{"content": "c1", "chunk_index": 0}],
    )
    assert no_token_res.status_code == 401

    ok_res = client.post(
        f"/api/v1/internal/chunks/?document_id={doc.id}",
        headers={"x-internal-token": "test-internal-token"},
        json=[{"content": "c1", "chunk_index": 0}, {"content": "c2", "chunk_index": 1}],
    )
    assert ok_res.status_code == 200
    assert ok_res.json()["count"] == 2
