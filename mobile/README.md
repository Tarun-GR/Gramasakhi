# GramSakhi Android Client

React Native / Expo TypeScript client for the **existing** GramSakhi backend.

**Phase 2 (current):** OTP authentication, JWT session management, protected routing.  
**Not yet:** chat, RAG, eligibility, voice, push notifications.

## Prerequisites

- Node.js 20+ (tested with v24)
- npm
- [Android Studio](https://developer.android.com/studio) + emulator **or** a physical Android device with [Expo Go](https://expo.dev/go)
- GramSakhi backend running (default dev: port `8000`)

## Quick start

```powershell
cd mobile
npm install
copy .env.example .env
npm run typecheck
npm run android
```

## API configuration

Set `EXPO_PUBLIC_API_BASE_URL` in `.env` (see `.env.example`):

| Environment | Typical URL |
|-------------|-------------|
| Android emulator → host PC | `http://10.0.2.2:8000` |
| Physical device (same Wi‑Fi) | `http://<your-lan-ip>:8000` |
| Production | `https://api.your-domain.example` |

The client calls `${API_ORIGIN}/api/...` to match the web app.

**Important:** Android emulators cannot reach the host using `127.0.0.1`. Use `10.0.2.2` instead.

**Production enforcement:** the `10.0.2.2` fallback only applies to development (`__DEV__`) builds.
A production build throws at startup unless `EXPO_PUBLIC_API_BASE_URL` is set, and refuses
`10.0.2.2` / `localhost` / `127.0.0.1` values (see `src/api/config.ts`).

No backend credentials belong in the mobile bundle.

## Navigation

```
Splash (/) → Landing (/landing) → Login (/login) → OTP (/otp) → Chat (/chat, protected)
```

- Authenticated users skip landing/login and go to `/chat` after splash bootstrap.
- Unregistered phones (OTP verified but no account) see a message to register via the web app.

## Secure storage

Access tokens use `expo-secure-store` via `src/storage/authTokens.ts`. OTP codes are **not** persisted.

## Project layout

```
mobile/
├── app/                 # Expo Router screens
├── src/
│   ├── api/             # Typed API client
│   ├── components/      # Shared UI
│   ├── hooks/
│   ├── navigation/
│   ├── services/
│   ├── storage/         # Secure token abstraction
│   ├── theme/           # GramSakhi design tokens
│   ├── types/
│   └── utils/
├── app.config.ts
├── .env.example
└── package.json
```

## Scripts

| Command | Purpose |
|---------|---------|
| `npm start` | Expo dev server |
| `npm run android` | Open on Android |
| `npm run typecheck` | TypeScript validation |

## Backend / web protection

This mobile client does **not** modify:

- `backend/`
- `frontend/gramsakhi/`

Verify after changes:

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend\gramsakhi
npm run build
```

## Mobile Phase 2 — authentication

- Real OTP send via `POST /api/auth/otp/send`
- Real OTP verify via `POST /api/auth/otp/verify`
- JWT stored in `expo-secure-store` (never AsyncStorage)
- Session restore on launch via `GET /api/chat/conversations?limit=1`
- Protected `/chat` route with logout
- Unregistered phones see a registration message (web registration required)

## Mobile Phase 3 — text chat

- Conversation list, load, and create via existing `/api/chat/*` endpoints
- Message send via `POST /api/chat` (backend RAG — no local intelligence)
- Session conversation ID restored from SecureStore on reload
- History load is read-only (no RAG/LLM on resume)
- Race-condition guards (`chatGeneration`, `loadRequestSeq`, `sendRequestSeq`)
- 401 clears auth + chat state and returns to login
- Minimal rendering of sources and assistance metadata

## Mobile Phase 4 — voice input and output

- STT via `POST /api/chat/voice/transcribe` (multipart `audio`, optional `language_hint`)
- TTS via `POST /api/chat/voice/synthesize` (`response_language` in JSON body)
- Android records `audio/webm`; iOS records WAV (backend accepts both)
- Transcription flows through existing `ChatContext.sendMessage()` → `/api/chat`
- Temporary audio files deleted after upload/playback
- Microphone permission via `expo-audio` plugin

## Mobile Phase 5 (not in this release)

- Dedicated eligibility/guidance/action-plan mobile screens
- Conversation search/rename/delete
- History pagination
- Mobile language selector

- Voice STT/TTS
- Dedicated eligibility/guidance/action-plan mobile screens
- Push notifications
- Offline mode

## License

Same as parent GramSakhi repository.
