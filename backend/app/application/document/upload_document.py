from sqlalchemy.orm import Session
import os
from fastapi import UploadFile

from app.models.document import Document
from app.models.document_job import DocumentJob

from app.services.file_extractor import (
    extract_text_from_pdf,
    extract_text_from_txt,
    extract_text_from_docx,
)

from app.services.event_publisher import publish_document_uploaded


async def handle_upload_document(
    db: Session,
    file: UploadFile,
    user_id: int,
    workspace_id: int | None = None,
):
    UPLOAD_DIR = "uploaded_files"
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    file_path = os.path.join(UPLOAD_DIR, file.filename)

    # save file
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # create document
    document = Document(
        filename=file.filename,
        file_type=file.content_type,
        user_id=user_id,
        workspace_id=workspace_id,
        status="uploaded",
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    # extract text
    if file.filename.endswith(".pdf"):
        raw_text = extract_text_from_pdf(file_path)
    elif file.filename.endswith(".txt"):
        raw_text = extract_text_from_txt(file_path)
    elif file.filename.endswith(".docx"):
        raw_text = extract_text_from_docx(file_path)
    else:
        raw_text = ""

    document.raw_text = raw_text
    db.commit()
    db.refresh(document)

    # create job
    job = DocumentJob(
        document_id=document.id,
        job_type="process_document",
        requested_by_user_id=user_id,
        payload={"filename": document.filename, "file_type": document.file_type},
    )
    db.add(job)
    db.commit()

    # publish event
    publish_document_uploaded(
        document_id=document.id,
        user_id=user_id
    )

    return document
