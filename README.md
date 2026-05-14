# PaperMind

PaperMind là hệ thống quản lý bài báo khoa học có tích hợp AI:
- Upload và quản lý tài liệu theo workspace (sổ tay).
- Tóm tắt tài liệu theo nhiều phong cách.
- Hỏi đáp theo ngữ cảnh tài liệu (RAG).
- Gợi ý tài liệu theo tác giả / method từ Neo4j recommendation graph.

## Kiến trúc chính

- `frontend`: React + Vite
- `backend`: FastAPI
- `neo4j-user`: lưu graph tài liệu người dùng (mới hoàn toàn)
- `neo4j-rec`: graph recommendation toàn cục (load từ `neo4j.dump`)

## Cổng dịch vụ (local)

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000/api/v1`
- Backend docs: `http://localhost:8000/docs`
- Neo4j User (Browser): `http://localhost:7476`
- Neo4j User (Bolt): `bolt://localhost:7689`
- Neo4j Recommendation (Browser): `http://localhost:7477`
- Neo4j Recommendation (Bolt): `bolt://localhost:7690`

## Chuẩn bị môi trường

1. Cài Docker + Docker Compose.
2. Đảm bảo file dump recommendation tồn tại:
   - `/home/nguyenducthang/neo4j.dump`
3. Cấu hình env backend:
   - `backend/.env`

Ví dụ biến Neo4j quan trọng:

```env
NEO4J_URI=bolt://neo4j-user:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j

NEO4J_REC_URI=bolt://neo4j-rec:7687
NEO4J_REC_USER=neo4j
NEO4J_REC_PASSWORD=password
NEO4J_REC_DATABASE=neo4j
```

## Chạy bằng Docker

Từ thư mục dự án:

```bash
cd ~/ai-paper-system

# Build + chạy toàn bộ
Docker compose up -d --build
```

Kiểm tra trạng thái:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

## Rebuild nhanh khi đổi code

- Rebuild backend + frontend:

```bash
docker compose up -d --build backend frontend
```

- Đảm bảo 2 Neo4j đang chạy:

```bash
docker compose up -d neo4j-user neo4j-rec
```

## Recommendation flow (backend)

Endpoint:

- `GET /api/v1/cms/documents/{document_id}/recommendations`

Pipeline ưu tiên:

1. Entity-based (`author + method`) từ artifact JSON.
2. Fallback theo author.
3. Fallback graph recommender (seed từ DOI/title).
4. Last resort metadata nội bộ.

Response item có `recommendation_type` để frontend tách tab:
- `author`
- `method`

## Một số lệnh hữu ích

- Log backend:

```bash
docker logs -f ai-paper-backend
```

- Kiểm tra Neo4j user trống:

```bash
docker exec ai-paper-neo4j-user cypher-shell -u neo4j -p password "MATCH (n) RETURN count(n) AS nodes"
```

- Kiểm tra Neo4j recommendation có dữ liệu:

```bash
docker exec ai-paper-neo4j-rec cypher-shell -u neo4j -p password "MATCH (p:Paper) RETURN count(p) AS papers"
```

## Lưu ý

- Không commit secret thật trong `.env`.
- Nếu thay đổi schema DB, chạy migration tương ứng trước khi deploy.
