# Frontend ↔ deployed backend

## Backend (production)

- **Base URL:** `https://gramasakhi.onrender.com`
- **Health:** `GET /health` → `{"status":"ok","service":"gramsakhi"}`
- **Citizen API prefix:** `/api` (e.g. `POST /api/chat/`, `POST /api/auth/otp/send`)

## Frontend configuration

| Environment | Variable | Value |
|-------------|----------|--------|
| Local dev | `VITE_API_BASE_URL` | `http://127.0.0.1:8000` (see `frontend/gramsakhi/.env.example`) |
| Production build | `VITE_API_BASE_URL` | `https://gramasakhi.onrender.com` (see `.env.production.example`) |

Resolution lives in `frontend/gramsakhi/src/services/api-config.js`. Production builds fall back to the Render URL if `VITE_API_BASE_URL` is unset.

### Local UI against deployed API

```powershell
cd frontend/gramsakhi
# Create .env.local (gitignored) with:
# VITE_API_BASE_URL=https://gramasakhi.onrender.com
npm run dev
```

The Render backend must allow your browser origin in **CORS** (`BACKEND_CORS_ORIGINS`). Default backend settings include `http://127.0.0.1:5173` unless production overrides the list to frontend-only hosts.

## Authentication (citizen)

- OTP send: `POST /api/auth/otp/send` `{ "phone_number": "..." }`
- OTP verify: `POST /api/auth/otp/verify` → `{ "accessToken", "citizen_account_id", ... }`
- Token is kept **in memory only** (tab session); `Authorization: Bearer <accessToken>` on protected routes.
- 401 on non-auth routes clears session and redirects to `/citizen/login`.

## Chat

- Request: `POST /api/chat/` body matches backend `ChatRequest`:
  - `message`, optional `conversation_id`, `language` (`EN`|`HI`|`KN`), optional voice fields.
- Response: `answer`, `conversation_id`, `sources`, `official_sources`, assistance metadata.
- UI mapping: `gramasakhi-ui/lib/api/backend-adapter.js`, `chat-store.js` (no mock fallback in production).

## CORS (manual on Render)

When the static frontend is hosted (e.g. `https://gramsakhi.example.com`), set on the **backend** service:

```env
BACKEND_CORS_ORIGINS=["https://gramasakhi-1.onrender.com","http://127.0.0.1:5173"]
```

The backend **defaults** already include `https://gramasakhi-1.onrender.com` and local Vite origins. Set this variable only to **replace** the list (JSON array or comma-separated URLs). Do not use `*` with credentials.

## Build

```powershell
cd frontend/gramsakhi
$env:VITE_API_BASE_URL="https://gramasakhi.onrender.com"
npm ci
npm run build
```

Output: `frontend/gramsakhi/dist`

## OTP on deployed stack

Production backend uses `OTP_DELIVERY_MODE=sms` without a wired SMS provider: **send returns 200** but the OTP is **not** delivered for normal numbers.

For **FYP review**, enable allowlisted demo login on the backend only: [FYP_DEMO_LOGIN.md](../backend/docs/FYP_DEMO_LOGIN.md). Do not enable `OTP_DEV_POPUP` on Render.

Local developers: [LOCAL_OTP_TESTING.md](../backend/docs/LOCAL_OTP_TESTING.md).

Chat timeouts on Render: [CLOUD_CHAT.md](../backend/docs/CLOUD_CHAT.md).

## Verification checklist (manual)

- [ ] `GET https://gramasakhi.onrender.com/health` returns 200
- [ ] OTP login on production requires real SMS (not configured yet)
- [ ] Local login with `dev_popup` against `127.0.0.1:8000`
- [ ] Chat returns real `answer` JSON (not client-side mock)
- [ ] Browser network tab shows requests to `gramasakhi.onrender.com/api/...`
