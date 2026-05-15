# PaperMind

PaperMind là hệ thống quản lý bài báo khoa học tích hợp AI (RAG + KG + recommendation).

## Kiến trúc

- `frontend`: React + Vite
- `backend`: FastAPI
- `Neo4j Aura`: user-doc graph + recommendation graph
- `PostgreSQL`: metadata và dữ liệu nghiệp vụ

## Yêu cầu môi trường

- Node.js 20+
- Python 3.11+
- PostgreSQL đang hoạt động
- 2 Neo4j Aura instance (hoặc 2 database) đã tạo sẵn

## Cấu hình

Tạo `backend/.env` từ `backend/.env.example` và điền tối thiểu:

```env
DATABASE_URL=postgresql://...
SECRET_KEY=...
INTERNAL_API_TOKEN=...

NEO4J_URI=neo4j+s://<aura-user-doc>.databases.neo4j.io
NEO4J_USER=<username>
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=<database>
NEO4J_USER_DOC_DB=<database>

NEO4J_REC_URI=neo4j+s://<aura-rec>.databases.neo4j.io
NEO4J_REC_USER=<username>
NEO4J_REC_PASSWORD=<password>
NEO4J_REC_DATABASE=<database>
```

## Chạy local (không Docker)

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## API quan trọng

- Docs: `http://127.0.0.1:8000/docs`
- Recommendation: `GET /api/v1/cms/documents/{document_id}/recommendations`

## Lưu ý

- Repo đã bỏ Docker/Compose cho Neo4j, chỉ dùng Neo4j Aura qua biến `NEO4J_*`.
- Không commit secret thật trong file env.
