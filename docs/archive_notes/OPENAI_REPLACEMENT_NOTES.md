# OpenAI / ChatGPT API Replacement Notes

## What changed

- Added `backend/app/agent/ai_client.py`.
- OpenAI is now the default provider through `AI_PROVIDER=openai`.
- The backend uses `OPENAI_API_KEY` and `OPENAI_MODEL`.
- Existing AI call sites now import `ai_generate_text`.
- `backend/app/agent/gemini_client.py` remains as a compatibility wrapper only, so old imports do not crash.
- `/ai/status` now checks OpenAI by default.
- Docker Compose now passes OpenAI environment variables to the backend container.
- `.env` and `.env.example` now use OpenAI placeholders. The old Gemini key was removed from `.env`.

## Recommended environment

```env
AI_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT=120
OPENAI_INTENT_TIMEOUT=60
OPENAI_DOCUMENT_TIMEOUT=240
OPENAI_STATUS_TIMEOUT=15
```

## Where OpenAI is used

OpenAI now handles:

- normal ChatGPT-style chat
- intent classification
- query planning
- plan criticism
- semantic typo rewrite
- final answer generation
- PDF rich extraction table
- Excel rich extraction table

## Optional Gemini fallback

Gemini is not the default anymore. It is only kept for backward compatibility. Set `AI_PROVIDER=gemini` only if you intentionally want to use Gemini.
