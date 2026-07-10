# OKF Weaver — frontend

Next.js (App Router) thin client: paste a schema, stream generation, review with
confidence badges, download the OKF bundle `.zip`. All logic lives in the
backend; this only calls the API.

## Develop

```bash
npm install
cp .env.example .env.local   # point NEXT_PUBLIC_API_BASE at the backend
npm run dev                  # http://localhost:3000
npm run build                # production build (also run in CI)
```

`NEXT_PUBLIC_API_BASE` defaults to `http://127.0.0.1:8000`.
