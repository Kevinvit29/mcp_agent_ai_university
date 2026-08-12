# Gemini Restore Notes

This package switches the AI provider back to Gemini as the default.

## Main `.env`

```env
AI_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT=120
GEMINI_INTENT_TIMEOUT=60
GEMINI_DOCUMENT_TIMEOUT=240
GEMINI_STATUS_TIMEOUT=15
```

## What Gemini now handles

- Normal chat / ChatGPT-style answers
- Intent classification
- Database query planning
- Final response generation
- Rich PDF extraction
- Rich Excel extraction

OpenAI support is still kept in `backend/app/agent/ai_client.py`, but it will not be used unless you set `AI_PROVIDER=openai`.

## Test

```bash
docker compose down --remove-orphans
docker compose up --build
curl http://localhost:8000/ai/status
```

Expected result:

```json
{
  "provider": "gemini",
  "connected": true,
  "model": "gemini-2.5-flash",
  "reply": "ok"
}
```
