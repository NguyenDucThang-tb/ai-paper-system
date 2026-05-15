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
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- `NEO4J_REC_URI`, `NEO4J_REC_USER`, `NEO4J_REC_PASSWORD`, `NEO4J_REC_DATABASE`

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
