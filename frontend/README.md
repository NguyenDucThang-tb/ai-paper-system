# AI Paper Frontend (Local)

## Cài và chạy local

```bash
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## Kết nối backend local

Tạo file `.env.local` trong thư mục `frontend`:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

## Build kiểm tra local

```bash
npm run build
npm run preview
```
