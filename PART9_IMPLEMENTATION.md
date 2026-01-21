# Part 9: Conversational Chat + Research Consent Gate

## Overview

This change adds a persistent chat layer with explicit research consent. The assistant behaves like a normal chat system by default, and only starts the research pipeline when the user explicitly confirms.

Key guarantees:
- Every user message is stored immediately.
- Every assistant response is stored (including offers, errors, and run-start events).
- Research runs only start after explicit consent.
- Conversation history is replayable from the database with cursor pagination.

## Message Types

All chat messages are stored in `chat_messages` with `role` and `type`:

- `chat`: normal conversational content
- `pipeline_offer`: assistant asking for consent to start the research pipeline
- `action`: user actions (button clicks or action tokens)
- `run_started`: assistant confirmation that a run was created
- `error`: assistant error message when something fails

Structured payloads live in `content_json`:
- `pipeline_offer`: `{ offer: { prompt_preview, actions: [{ id, label }] } }`
- `action`: `{ action_id, label }`
- `run_started`: `{ run_id }`

## Consent Gate Flow

1) User sends a message.
2) Router decides:
   - `chat` (quick response)
   - `offer_pipeline` (ask for consent)
3) If `offer_pipeline`, the assistant replies:
   "Do you want me to run the research pipeline and generate a cited report?"
4) User responds with:
   - `__ACTION__:run_pipeline` (YES)
   - `__ACTION__:quick_answer` (NO)
   - or a text reply (yes/no/ambiguous/new-topic)
5) YES creates a run and returns a `run_started` message.
6) NO returns a quick chat response.
7) Ambiguous responses trigger one clarifier. If ambiguous twice, default to quick answer.
8) New topics clear the pending action and route normally.

## History Storage and Replay

Persistence tables:

`chat_conversations`
- Tracks conversation metadata and pending consent state.
- `pending_action_json` stores the current consent gate state.
- `last_action_json` stores the most recent run start for idempotency.

`chat_messages`
- Stores every message with a stable order (`created_at`, `id`).
- Cursor pagination uses `(created_at, id)` for deterministic replay.

Replay strategy:
- The UI loads messages in oldest-first order.
- Pipeline offers and run-start events render deterministically from `type` + `content_json`.

## API Endpoints

Backend endpoints:
- `POST /chat/conversations`
- `GET /chat/conversations`
- `GET /chat/conversations/{conversation_id}/messages`
- `POST /chat/send`

All queries are tenant-scoped and require `tenant_id` filtering.

## UX Notes

- The chat UI always shows messages from the database.
- Pipeline offers render action buttons with explicit consent.
- Run started messages link to the run viewer (`/runs/:run_id`).
- Quick answers never include citations.
