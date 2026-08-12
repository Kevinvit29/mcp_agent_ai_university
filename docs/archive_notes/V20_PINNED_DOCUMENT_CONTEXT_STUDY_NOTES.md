# V20 – Pinned Document Context and Study Notes

## Why the old answer failed
The file card could show a saved summary, but asking “What is this file about? (filename)” sent a new text-only search. Filename punctuation and generic words could make the agent re-match the wrong record or fall through to a general answer.

## What changed
- Ask actions now attach `document_id` and `document_scope`.
- The backend uses `document_by_id` with normal role/PDPA filtering.
- The final answer is formatted directly from stored summary, extracted text, and structured notes.
- AI Notes is renamed **Study notes**, clearly described as an AI-organized learning aid.
- **Data table** is explicitly the source-row/chunk view.
