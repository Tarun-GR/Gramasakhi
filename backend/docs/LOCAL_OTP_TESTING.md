# Local OTP testing (development only)

## Why production `POST /api/auth/otp/send` returns 200 but no SMS

On Render (`APP_ENV=production`, `OTP_DELIVERY_MODE=sms`):

1. The handler **always** creates a valid `otp_verifications` row and returns `"OTP verification code sent."`
2. `dispatch_otp_sms()` calls `deliver_otp_via_sms()` in `otp_sms.py`, which is a **stub** — it logs `otp_sms_dispatch` with masked phone only (**no OTP**, no provider HTTP call).
3. `OTP_CONSOLE_SIMULATOR_ENABLED` and `dev_popup` are **disabled** in production, so the OTP is **not** printed to logs, files, or JSON.

Verify fails with **400** if the user guesses wrong — expected until a real SMS provider is integrated.

**Do not** enable `dev_popup` or console OTP on the public backend.

---

## Recommended local workflow (UI + terminal)

Use **local backend** + **local frontend** (`http://127.0.0.1:5173`).

### Option A — Dev popup (side panel on verify page)

`backend/.env`:

```env
APP_ENV=development
OTP_DELIVERY_MODE=dev_popup
OTP_DEV_POPUP_ENABLED=true
OTP_CONSOLE_SIMULATOR_ENABLED=true
```

Commands:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
cd frontend/gramsakhi
# .env.local: VITE_API_BASE_URL=http://127.0.0.1:8000
npm run dev
```

Flow: **Send OTP** → response includes `dev_otp` → **DevOtpSidePanel** shows the code → verify.

See [OTP_DEV_POPUP.md](./OTP_DEV_POPUP.md).

### Option B — SMS mode + terminal / mirror file (no OTP in API)

```env
APP_ENV=development
OTP_DELIVERY_MODE=sms
OTP_DEV_POPUP_ENABLED=false
OTP_CONSOLE_SIMULATOR_ENABLED=true
```

After send, read OTP from:

- **Uvicorn terminal** (`VERIFICATION OTP` banner)
- **`backend/.dev_otp_last.txt`** (gitignored; dev only)

API response has **no** `dev_otp` field.

---

## Production vs local (summary)

| Setting | Local (demo) | Production (Render) |
|---------|----------------|---------------------|
| `APP_ENV` | `development` | `production` |
| `OTP_DELIVERY_MODE` | `dev_popup` or `sms` | `sms` |
| `OTP_DEV_POPUP_ENABLED` | `true` if `dev_popup` | `false` |
| `OTP_CONSOLE_SIMULATOR_ENABLED` | `true` (optional) | `false` |
| OTP in JSON | Only if `dev_popup` | **Never** |
| OTP in logs | Only if dev + console enabled | **Never** |

---

## Optional: dev HTTP lookup

`GET /api/auth/otp/dev?phone_number=...` with header `X-Dev-OTP-Key` when `OTP_DEV_RETRIEVAL_ENABLED=true` (non-production). Prefer popup or terminal for FYP demos.

---

## Deployed frontend + deployed backend

`https://gramasakhi-1.onrender.com` → `https://gramasakhi.onrender.com` **cannot** use dev popup until real SMS works. CORS is configured; OTP delivery is the blocker.
