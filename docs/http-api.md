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

## WebSocket Realtime

Use `/ws` when a client needs bidirectional agent trace and control messages on
one connection. The server sends a `hello` message after the connection is
accepted.

```javascript
const ws = new WebSocket("ws://127.0.0.1:8000/ws");

ws.onmessage = (event) => {
  console.log(JSON.parse(event.data));
};
```

When HTTP authentication is enabled, browser clients may pass the credential in
the connection URL:

```javascript
const ws = new WebSocket("ws://127.0.0.1:8000/ws?api_key=secret");
```

`access_token` is also accepted for OAuth bearer-style credentials. Non-browser
clients can continue to use `Authorization: Bearer <token>` or
`X-Evernight-API-Key: <api-key>` headers.

All messages use the same envelope:

```json
{
  "message_type": "heartbeat",
  "message_id": "heartbeat-1",
  "correlation_id": null,
  "run_id": null,
  "payload": {},
  "metadata": {}
}
```

The important envelope fields are:

- `message_type`: one of `hello`, `heartbeat`, `heartbeat_ack`, `agent_trace`,
  `agent_control`, `tool_approval`, `client_event`, or `error`
- `message_id`: client or server message id
- `correlation_id`: response message link back to the triggering message id
- `run_id`: agent run id when the message is tied to a run

Send a heartbeat:

```json
{
  "message_type": "heartbeat",
  "message_id": "heartbeat-1",
  "heartbeat": {"sequence": 1}
}
```

The server replies:

```json
{
  "message_type": "heartbeat_ack",
  "correlation_id": "heartbeat-1",
  "heartbeat": {"sequence": 1, "metadata": {}},
  "payload": {},
  "metadata": {}
}
```

The server also sends heartbeat messages on idle connections. Clients should
reply with `heartbeat_ack` using the heartbeat message id as `correlation_id`.
If no client message is received before the heartbeat timeout, the server closes
the connection with close code `4000` and reason `heartbeat_timeout`.

Start an agent run by sending a `client_event` named `agent_run.start`. The
payload is an `AgentRunRequest`.

```json
{
  "message_type": "client_event",
  "message_id": "start-1",
  "client_event": {
    "event_name": "agent_run.start",
    "payload": {
      "provider_id": "main",
      "context_id": "ctx-1",
      "model_id": "gpt-4.1-mini",
      "messages": [
        {
          "role": "user",
          "content": [{"type": "text", "text": "Answer and stop."}]
        }
      ],
      "metadata": {"run_id": "run-1"}
    }
  }
}
```

Trace events are sent as `agent_trace` messages. Their `correlation_id` points
to the start or resume message that produced the stream.

```json
{
  "message_type": "agent_trace",
  "correlation_id": "start-1",
  "run_id": "run-1",
  "trace_event": {
    "event_type": "run_started",
    "summary": "Agent run started",
    "metadata": {}
  },
  "payload": {"sequence": 1, "replayed": false},
  "metadata": {}
}
```

Each trace message includes replay metadata in `payload`:

- `sequence`: 1-based trace sequence for the run when the server can resolve it
- `replayed`: `false` for live stream messages, `true` for reconnect replay

Reconnect by sending a `client_event` named `agent_run.subscribe`. The server
subscribes the connection to future trace broadcasts for the run and replays
stored trace events after the supplied sequence.

```json
{
  "message_type": "client_event",
  "message_id": "subscribe-1",
  "client_event": {
    "event_name": "agent_run.subscribe",
    "payload": {
      "run_id": "run-1",
      "after_sequence": 1
    }
  }
}
```

The example above replays trace events with sequence `2` and above, then keeps
the connection subscribed to live trace messages for `run-1`.

Approve a paused tool call with `tool_approval`:

```json
{
  "message_type": "tool_approval",
  "message_id": "approval-1",
  "tool_approval": {
    "run_id": "run-1",
    "decision": {
      "approval_id": "approval-1",
      "tool_call_id": "tool-call-1",
      "status": "approved",
      "metadata": {}
    },
    "metadata": {}
  }
}
```

The WebSocket route uses a connection manager. Outbound messages are serialized
through a bounded queue, agent trace streams run in background tasks, and the
receive loop stays available for heartbeats and approval messages while a stream
is active. Disconnecting cancels active stream tasks and removes run
subscriptions for that connection.

Control an active run with `agent_control`. `pause` moves a running persisted
run to `paused`, cancels the active stream task, and broadcasts a `run_paused`
trace event.

```json
{
  "message_type": "agent_control",
  "message_id": "pause-1",
  "agent_control": {
    "run_id": "run-1",
    "action": "pause",
    "reason": "user paused"
  }
}
```

`cancel` moves a running or paused persisted run to `canceled`, cancels the
active stream task, clears pending tool approvals, and broadcasts a
`run_stopped` trace event with reason `canceled`.

```json
{
  "message_type": "agent_control",
  "message_id": "cancel-1",
  "agent_control": {
    "run_id": "run-1",
    "action": "cancel",
    "reason": "user canceled"
  }
}
```

`resume` restarts a manually paused run from its stored request. For
tool-approval pauses, `resume` maps to resume-with-no-approvals; use
`tool_approval` when a pending approval decision is required.

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
