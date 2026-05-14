# Deploy AI Paper System theo mô hình App Server + External LLM Server

Mô hình chốt:
- App server chạy `backend + frontend` bằng Docker.
- LLM server chạy riêng tại `http://n3.ckey.vn:2409`.
- Backend chỉ gọi HTTP tới LLM server, không chạy model local.

## 1) Chuẩn bị môi trường trên server

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

## 2) Upload source code lên server

```bash
# Ví dụ dùng git
git clone <repo-url> ai-paper-system
cd ai-paper-system
```

## 3) Cập nhật lại module từ zip (nếu cần)

```bash
# copy 2 file zip vào server trước
rm -rf ingestion ai_module
unzip -q /path/to/ingestion.zip
unzip -q /path/to/ai_module.zip
```

## 4) Cấu hình backend env

```bash
cp deploy.env.example backend/.env
nano backend/.env
```

Các biến bắt buộc cần điền:
- `SECRET_KEY`
- `INTERNAL_API_TOKEN`
- `DATABASE_URL`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` (nếu dùng Google login)
- `SMTP_*` / `MAIL_*` (nếu dùng OTP email)

Biến GPU quan trọng đã set mẫu:
- `LLM_BACKEND=vllm`
- `VLLM_BASE_URL=http://n3.ckey.vn:2409`
- `VLLM_MODEL_NAME=qwen2.5:7b`

## 5) Build và chạy liên tục (app-only)

```bash
./scripts/deploy_gpu_server.sh
```

Script sẽ:
- build backend + frontend
- chạy `docker compose -f docker-compose.app-only.yml up -d`
- bật `restart: unless-stopped` để tự chạy lại khi reboot

## 6) Kiểm tra

```bash
docker compose -f docker-compose.app-only.yml ps
docker compose -f docker-compose.app-only.yml logs -f backend
```

## 7) Mở port / reverse proxy

Mặc định:
- Backend: `:8000`
- Frontend: `:5173`

Khuyến nghị production: đặt Nginx/Caddy trước frontend+backend và dùng HTTPS domain thật.

## 8) Test kết nối LLM server từ app server

```bash
curl -s http://n3.ckey.vn:2409/v1/models
curl -s -X POST http://n3.ckey.vn:2409/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:7b",
    "messages": [{"role":"user","content":"ping"}],
    "temperature": 0.1
  }'
```
