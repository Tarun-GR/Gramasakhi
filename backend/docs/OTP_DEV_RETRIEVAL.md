# Development OTP retrieval

Manual workflow for local Android / Expo testing when no SMS provider is configured.

**Production behavior is unchanged.** `/api/auth/otp/send` never returns the OTP. This endpoint is disabled unless every gate below is satisfied.

## Requirements

All of the following must be true:

1. `APP_ENV` is **not** `production`
2. `OTP_DEV_RETRIEVAL_ENABLED=true`
3. `OTP_DEV_RETRIEVAL_KEY` is set to a local secret (not committed)

## Setup

1. Add to `backend/.env` (generate your own random key locally):

```env
APP_ENV=development
OTP_DEV_RETRIEVAL_ENABLED=true
OTP_DEV_RETRIEVAL_KEY=<your-random-local-secret>
```

2. Restart the backend.

3. Send an OTP from the Android app (or `POST /api/auth/otp/send`).

4. Retrieve the active OTP manually:

```powershell
$phone = "9876543210"
$key = "<your-random-local-secret>"
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/auth/otp/dev?phone_number=$phone" `
  -Headers @{ "X-Dev-OTP-Key" = $key }
```

Example response:

```json
{
  "otp": "123456",
  "expires_at": "2026-08-22T14:30:00+00:00",
  "phone_number": "***3210"
}
```

## Security notes

- Returns **404 Not found** when disabled, in production, or when the dev key is missing/incorrect (same response shape).
- Does **not** consume the OTP, increment attempt counts, or bypass expiry.
- Does **not** log the OTP.
- Hidden from OpenAPI unless the feature is fully enabled at process start.
- Intended for developer/manual testing only — not for mobile or web client integration.
