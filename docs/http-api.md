# EvernightAI HTTP API

This guide shows the shortest working HTTP flow. The same bodies are also used
as Swagger examples.

Start the local app:

```bash
EVERNIGHTAI_DATABASE_PATH=".evernight/runtime.sqlite3" \
EVERNIGHTAI_FILESYSTEM_ROOT="$PWD" \
.venv/bin/python -m uvicorn EvernightAI.bootstrap.http:create_app --factory --reload
```

Open Swagger at `http://127.0.0.1:8000/docs`.

To serve the compiled frontend from the same HTTP process, build the frontend
first and point the HTTP app at the generated static directory:

```bash
cd frontend
pnpm run build
cd ..
EVERNIGHTAI_DATABASE_PATH=".evernight/runtime.sqlite3" \
EVERNIGHTAI_FILESYSTEM_ROOT="$PWD" \
EVERNIGHTAI_HTTP_STATIC_FILES_PATH="frontend/dist" \
.venv/bin/python -m uvicorn EvernightAI.bootstrap.http:create_app --factory --reload
```

## Register A Provider

Create a provider id. Later requests refer to this id as `main`.

```bash
curl -X POST http://127.0.0.1:8000/providers \
  -H 'content-type: application/json' \
  -d '{
    "provider_id": "main",
    "name": "Main provider",
    "type": "openai",
    "api_key": "sk-...",
    "base_url": "https://api.openai.com/v1",
    "model": {
      "gpt-4.1-mini": {
        "model_id": "gpt-4.1-mini",
        "capabilities": ["chat"]
      }
    }
  }'
```

Provider model listing asks the provider instance for remote models when the
adapter supports it. If discovery is unavailable, the runtime falls back to the
models declared locally in configuration. Chat requests may still use a model id
that is not declared locally.

## One-Off Chat

Use `/chat` when you do not want stored history.

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'content-type: application/json' \
  -d '{
    "provider_id": "main",
    "request": {
      "model_id": "gpt-4.1-mini",
      "messages": [
        {
          "role": "user",
          "content": [{"type": "text", "text": "Hello, give me a short answer."}]
        }
      ]
    }
  }'
```

Use `/chat/stream` with the same body for SSE streaming.

## Provider-Specific Metadata

Provider-specific controls belong in request `metadata`, not in the core
`ChatRequest` fields. Unknown metadata stays inside EvernightAI and is not sent
to the provider.

OpenAI-compatible chat and OpenAI Responses adapters currently support:

- `reasoning_effort`: `"low"`, `"medium"`, or `"high"`

Example:

```json
{
  "provider_id": "main",
  "request": {
    "model_id": "gpt-4.1-mini",
    "messages": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "Think carefully, then answer briefly."}]
      }
    ],
    "metadata": {
      "reasoning_effort": "high"
    }
  }
}
```

## Context Chat

Create a context when the server should store conversation history.

```bash
curl -X POST http://127.0.0.1:8000/contexts \
  -H 'content-type: application/json' \
  -d '{"context_id": "ctx-1", "messages": []}'
```

Then call `/chat/context`.

```bash
curl -X POST http://127.0.0.1:8000/chat/context \
  -H 'content-type: application/json' \
  -d '{
    "provider_id": "main",
    "context_id": "ctx-1",
    "model_id": "gpt-4.1-mini",
    "messages": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "Continue from the stored context."}]
      }
    ]
  }'
```

Use `/chat/context/stream` with the same body for SSE streaming. The streamed
assistant message is persisted after completion.

## Sessions

A session binds a user-facing conversation to a context, provider, and model.

```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{
    "session_id": "session-1",
    "title": "Planning chat",
    "context_id": "ctx-1",
    "provider_id": "main",
    "model_id": "gpt-4.1-mini"
  }'
```

Send a session message without repeating provider or model.

```bash
curl -X POST http://127.0.0.1:8000/sessions/session-1/chat \
  -H 'content-type: application/json' \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "Summarize our current plan."}]
      }
    ]
  }'
```

`provider_id` and `model_id` may be supplied on a session chat request. Request
values override the session defaults for that call.

## Agent Runs

Use agent runs when a request needs trace records, tool rounds, approvals, or
memory writing.

```bash
curl -X POST http://127.0.0.1:8000/agent-runs \
  -H 'content-type: application/json' \
  -d '{
    "provider_id": "main",
    "context_id": "ctx-1",
    "model_id": "gpt-4.1-mini",
    "messages": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "Answer and stop."}]
      }
    ],
    "max_tool_rounds": 0
  }'
```

Use `/agent-runs/stream` with the same body to receive trace events as SSE.

To allow tools and pause for approval, include tool definitions:

```json
{
  "provider_id": "main",
  "context_id": "ctx-1",
  "model_id": "gpt-4.1-mini",
  "messages": [
    {
      "role": "user",
      "content": [{"type": "text", "text": "Inspect the workspace if needed."}]
    }
  ],
  "tools": [
    {
      "tool_name": "write_file",
      "description": "Write text to a workspace file.",
      "parameters_schema": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "content": {"type": "string"}
        },
        "required": ["path", "content"]
      },
      "requires_approval": true
    }
  ],
  "max_tool_rounds": 2,
  "pause_on_approval": true
}
```

Resume a paused run with explicit approval decisions:

```bash
curl -X POST http://127.0.0.1:8000/agent-runs/run-1/resume \
  -H 'content-type: application/json' \
  -d '{
    "approvals": [
      {
        "approval_id": "approval-1",
        "tool_call_id": "tool-call-1",
        "status": "approved"
      }
    ]
  }'
```
