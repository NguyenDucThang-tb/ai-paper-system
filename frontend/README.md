# AI Paper Frontend (Vite + React)

## Run local

```bash
npm install
npm run dev
```

## Build production

```bash
npm run build
npm run preview
```

## Docker

Build image:

```bash
npm run docker:build
```

Run container:

```bash
npm run docker:run
```

Open: `http://localhost:8080`

Pass API URL at build time:

```bash
docker build -t ai-paper-frontend --build-arg VITE_API_BASE_URL=https://your-api-domain/api/v1 .
```

## Deploy to Vercel

Project settings:

- Framework Preset: `Vite`
- Build Command: `npm run build`
- Output Directory: `dist`

Environment Variable:

- `VITE_API_BASE_URL=https://your-api-domain/api/v1`
- On Vercel, set this variable for both `Production` and `Preview` environments.

`vercel.json` is configured for SPA rewrites so routes like `/login`, `/library`, `/document/:id` work after refresh.
