# AI Paper Frontend (Local)

## Cài và chạy local

```bash
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## Kết nối backend local

Tạo file `.env.local` trong thư mục `frontend`:

```bash
VITE_API_BASE_URL=https://triumphant-charisma-production-f2a9.up.railway.app/api/v1
```

## Build kiểm tra local

```bash
npm run build
npm run preview
```
