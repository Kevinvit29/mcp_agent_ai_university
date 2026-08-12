# Archived V22 — Persistent Document Context and Reading Guide Reliability

## Problem fixed

A file selected with **Ask** was cleared after the first user message. A follow-up like `explain` then went through generic semantic document search. Retrieval-only pseudo rows could outrank the real document and leak internal text such as a neural-agent score instead of explaining the file.

## Changes

- The selected file remains pinned across follow-up messages until the user clicks **Clear** or starts a new chat.
- Broad prompts such as `explain`, `explain this file`, and `what is this file about?` now use the stored document overview instead of a random source sentence.
- Targeted questions such as `What is torts?` still retrieve a concise grounded source excerpt.
- Retrieval-only neural pseudo rows are never preferred over a full stored document record and internal scores/agent metadata are not exposed in user-facing chat.
- File answers are not sent through a second naturalization pass that could lose document context.
- **Study notes** is now presented as **Reading guide**, with a clear statement that it is a learning aid based on extracted content, not the original source.

## Expected behavior

1. Click **Ask** for a file.
2. The composer shows `Pinned file: <filename>`.
3. Ask `What is this file about?` → a whole-file overview.
4. Ask `What is torts?` → a targeted answer grounded in the selected file.
5. Ask `explain` → continues to explain the same pinned file.
6. Click **Clear** to return to normal university/database chat.
