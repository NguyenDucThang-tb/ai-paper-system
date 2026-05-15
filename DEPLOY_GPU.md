# Deploy AI Paper System (No Docker, Aura-only)

## Mô hình

- App server chạy trực tiếp `backend + frontend` (systemd/pm2 tùy bạn).
- Neo4j dùng hoàn toàn Neo4j Aura (`neo4j+s://...`).
- LLM server có thể external qua endpoint OpenAI-compatible.

## 1) Cài dependency

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm
```

## 2) Lấy source

```bash
git clone <repo-url> ai-paper-system
cd ai-paper-system
```

## 3) Cấu hình env

```bash
cp deploy.env.example backend/.env
nano backend/.env
```

Bắt buộc:
- `DATABASE_URL`
- `SECRET_KEY`
- `INTERNAL_API_TOKEN`
- User graph:
  - `NEO4J_URI=neo4j+s://6d37f1fa.databases.neo4j.io`
  - `NEO4J_USER=neo4j` (hoặc `NEO4J_USERNAME=neo4j`)
  - `NEO4J_PASSWORD=I3Pzsg1gvUw2BCFsp3A6CjuhjjY9XIun1Fp6dsYJo3s`
  - `NEO4J_DATABASE=neo4j`
  - `NEO4J_USER_DOC_DB=neo4j`
- Recommendation graph:
  - `NEO4J_REC_URI=neo4j+s://65e82d44.databases.neo4j.io`
  - `NEO4J_REC_USER=65e82d44` (hoặc `NEO4J_REC_USERNAME=65e82d44`)
  - `NEO4J_REC_PASSWORD=76VhdpIq2of0DEJvrRlbtiW4N-FdMaq1rv6RB4dvvbM`
  - `NEO4J_REC_DATABASE=65e82d44`

## 4) Run backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 5) Run frontend

```bash
cd frontend
npm install
npm run build
npm run dev -- --host 0.0.0.0 --port 5173
```

## 6) Kiểm tra

- Backend docs: `http://<server>:8000/docs`
- Frontend: `http://<server>:5173`

## 7) Khuyến nghị production

- Chạy backend/frontend bằng `systemd`.
- Đặt Nginx/Caddy reverse proxy + HTTPS.
