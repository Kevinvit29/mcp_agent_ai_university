"""Compatibility wrapper for older imports.

The project uses backend/app/agent/ai_client.py. Gemini is the default provider
again, but the function names stay the same so older files do not break.
"""

from app.agent.ai_client import ai_generate_text, gemini_generate_text

__all__ = ["ai_generate_text", "gemini_generate_text"]
