# FYP public demo login (deployed)

For project review when SMS is not configured, enable **allowlisted demo OTP** on the production backend only for a dedicated demo citizen phone.

## Render environment variables (backend)

| Variable | Example | Notes |
|----------|---------|--------|
| `DEMO_LOGIN_ENABLED` | `true` | Set `false` after review to restore normal SMS-only behavior |
| `DEMO_LOGIN_PHONES` | `9999900001` | One dedicated 10-digit number (comma-separated for up to 3) |
| `DEMO_LOGIN_LABEL` | `FYP demo citizen` | Shown in the login UI |
| `OTP_DELIVERY_MODE` | `sms` | Keep default |
| `OTP_DEV_POPUP_ENABLED` | `false` | Do not enable on Render |
| `OTP_CONSOLE_SIMULATOR_ENABLED` | `false` | Do not enable on Render |

No frontend env vars are required; the UI reads `GET /api/auth/demo/info`.

## Provision the demo citizen (once)

Point `DATABASE_URL` at the same Postgres as Render (local shell with env from dashboard):

```powershell
cd backend
$env:DEMO_LOGIN_PHONES="9999900001"
.\.venv\Scripts\python.exe scripts\provision_demo_citizen.py --phone 9999900001
```

This creates/updates a row in `family_accounts` with OTP-only auth (random password hash).

## Reviewer flow

1. Open https://gramasakhi-1.onrender.com/citizen/login  
2. Click **Use FYP demo login** (or enter the allowlisted demo number).  
3. On verify, read the **FYP demo login code** panel and enter the 6-digit OTP.  
4. Open **Chat** and ask a scheme question (e.g. PM-KISAN, Shakti).

## Automated production acceptance (maintainers)

After deploy, confirm `GET /health/build` matches the intended Git commit, then run (uses allowlisted demo OTP once per run):

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\prod_chat_acceptance.py
```

Optional: pass a fresh citizen JWT with `--token` to skip OTP when rate limits apply (`AUTH_OTP_SEND_MAX_PER_WINDOW` is 5 per hour per phone).

## Security notes

- `demo_otp` appears in JSON **only** when `DEMO_LOGIN_ENABLED` and the requested phone is in `DEMO_LOGIN_PHONES`.
- Other numbers still get SMS mode with no OTP in the response.
- Demo citizens receive normal `token_use=citizen` JWTs; they cannot access `/api/v1/super-admin/*`.
- Disable `DEMO_LOGIN_ENABLED` when the public demo period ends.
