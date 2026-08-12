# Gemini Latest SDK Update

This version updates the university chatbot backend to the current Google GenAI SDK.

## Main changes

- Added `google-genai` to `backend/requirements.txt`.
- Updated Gemini default model from `gemini-2.0-flash` to `gemini-2.5-flash`.
- Added fallback model `gemini-2.5-flash-lite`.
- Rebuilt `backend/app/agent/ai_client.py` to use the current SDK pattern:
  - `from google import genai`
  - `client = genai.Client(api_key=...)`
  - `client.models.generate_content(...)`
- Added REST fallback using the official `generateContent` endpoint with `x-goog-api-key`.
- Added clearer error messages that show the attempted model and whether SDK or REST failed.

## Recommended .env

```env
AI_PROVIDER=gemini
GEMINI_API_KEY=your_real_google_ai_studio_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODEL=gemini-2.5-flash-lite
GEMINI_TIMEOUT=120
GEMINI_INTENT_TIMEOUT=60
GEMINI_DOCUMENT_TIMEOUT=240
GEMINI_STATUS_TIMEOUT=15
```

## Rebuild command

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up
```

## Test

```bash
curl http://localhost:8000/ai/status
```

Expected result should contain `connected: true` and a reply like `ok`.
