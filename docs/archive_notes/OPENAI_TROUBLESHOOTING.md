# OpenAI / ChatGPT API troubleshooting

If the app says OpenAI did not return a response, first check the backend status endpoint:

```bash
curl http://localhost:8000/ai/status
```

Expected result:

```json
{
  "provider": "openai",
  "connected": true,
  "model": "gpt-4.1-mini",
  "reply": "ok"
}
```

## Most common cause

The key is not inside the backend Docker container. Make sure `.env` is in the same folder as `docker-compose.yml` and contains your real key:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=sk-your-real-key-here
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT=120
OPENAI_INTENT_TIMEOUT=60
OPENAI_DOCUMENT_TIMEOUT=240
OPENAI_STATUS_TIMEOUT=15
```

Then rebuild:

```bash
docker compose down
docker compose up --build
```

Check inside the container without showing the full key:

```bash
docker compose exec backend python -c "import os; k=os.getenv('OPENAI_API_KEY',''); print('has key:', bool(k), 'starts:', k[:7])"
```

## If /ai/status is false

- `OPENAI_API_KEY is missing`: `.env` is wrong location, placeholder value, or Docker was not rebuilt.
- `HTTP 401`: API key is invalid or copied incorrectly.
- `HTTP 429`: billing/quota/rate limit problem.
- `model_not_found`: change `OPENAI_MODEL` to a model your account supports.
- Timeout/network error: backend container cannot reach `https://api.openai.com`.

This version keeps OpenAI variables only in `env_file: .env`, so Docker Compose will not overwrite your `.env` key with a blank value.
