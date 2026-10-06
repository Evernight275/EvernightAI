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

When running the frontend dev server separately, the Vite proxy defaults to
`http://127.0.0.1:8000`. Override it when the API listens elsewhere:

```bash
cd frontend
EVERNIGHTAI_API_PROXY_TARGET="http://127.0.0.1:9001" pnpm run dev
```

Production builds use same-origin API requests by default. Set
`VITE_EVERNIGHTAI_API_BASE` at build time for a separate API origin, or inject
`window.EVERNIGHTAI_API_BASE` at runtime; the runtime value takes precedence.
Separate origins must allow the frontend origin through CORS.

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

Creating an existing provider id returns `409`. Use the update endpoint to
change its configuration.

## Update A Provider

Read the editable configuration with `GET /providers/main/config`. The response
includes `base_url`, `discover_models`, `api_key_secret_ref`, declared models,
and `has_api_key`, but never the raw API key. This endpoint requires
`providers:get_config` when authorization is enabled.

Apply a partial update:

```bash
curl -X PATCH http://127.0.0.1:8000/providers/main \
  -H 'content-type: application/json' \
  -d '{
    "name": "Updated provider",
    "base_url": "https://your-provider.example/v1",
    "discover_models": false
  }'
```

The endpoint requires `providers:update` and returns `ProviderInfo`. The provider
id cannot change. Omitted fields retain their current values; supplying `model`
or `metadata` replaces that entire mapping. Preserve model dictionary aliases,
timeouts, capabilities, and metadata when editing a model map. An empty patch
leaves the current instance untouched. Missing providers return `404` and invalid
patches return `400`.

Omit both credential fields to retain credentials. Set `api_key` to replace the
key and clear its previous secret reference, or set `api_key_secret_ref`
to replace the reference and resolve its key. Do not supply both non-null values.
Set both fields to `null` to clear credentials; `base_url: null` restores the
adapter's default address. Other fields cannot be explicitly null.

SQLite runtimes persist configurations, including keys supplied by the web
settings page. Keys are encrypted into a secret reference using a local
`<database_path>.provider-key` file; provider payloads never contain plaintext
keys. The key file is created with owner-only permissions on POSIX and excluded
from version control. Keep it alongside the database when backing up or moving
the runtime. Missing or invalid key files produce a configuration error instead
of silently replacing the encryption key. Memory runtimes retain configuration
only for the lifetime of the process. Existing environment references, such as
`env:PROVIDER_API_KEY`, continue to work. Persisted configurations take precedence
over configuration-file defaults at startup.

Updates build and persist a replacement before publishing it. A failed update
keeps the existing provider available. In-flight calls and streams finish using
their original instance; subsequent calls use the updated configuration.
The web settings page exposes this flow under model service management.

### Enable Or Disable A Provider

Use the same update endpoint and `providers:update` permission:

```bash
curl -X PATCH http://127.0.0.1:8000/providers/main \
  -H 'content-type: application/json' \
  -d '{"is_enabled": false}'
```

Set `is_enabled` to `true` to enable it again. Repeating the current enabled state
alone leaves the instance untouched. Disabled providers remain in `GET /providers`
and can be inspected, edited, and deleted. Model and capability queries use their
local declarations without contacting the upstream service.

Disabling blocks new model calls with `ProviderDisabledError` (HTTP `409` for
ordinary chat requests; an SSE error event for streaming chat). Existing calls and
streams may finish before their instance closes. A multi-round agent run is
checked again at its next model call.
Disabling a provider does not cancel an agent run or its tools.

Creating or editing disabled configurations does not construct an adapter or
resolve credentials. Enabling resolves credentials and creates the adapter
through the provider factory; a failure keeps the configuration disabled. This
does not verify that the remote service will accept a subsequent request.

Persisted disabled configurations are restored as manageable records at startup,
even if their secret references cannot currently resolve. Their saved state takes
precedence over configuration-file defaults. SQLite also retains disabled
configurations created with a raw key, following the encryption rules above.

In web settings, each service has an enable/disable action. Chat model selection
offers enabled services only. A conversation whose selected service is disabled
keeps its history and draft, shows a notice, and requires re-enabling that service
or explicitly choosing another model before sending.

## Test A Provider Connection

`POST /providers/{provider_id}/test` requires the separate `providers:test`
permission and tests the currently saved provider configuration:

```json
{"model_id": "your-model-id"}
```

The model ID can be undeclared. This endpoint does not discover remote models.
It makes one ordinary chat call with the fixed prompt `Reply with OK.` and a
30-second timeout. It may incur provider charges; the short prompt is not a hard
output-token limit. It does not create sessions, compose context, select memories,
or execute tools. Normal provider telemetry and provider-default prompt caching
still apply; test responses are not reused.

A completed test returns HTTP `200` with `provider_id`, requested `model_id`,
`success`, and `elapsed_ms` (including model generation time). Success additionally
reports `response_model_id`. Upstream failures return `success: false` with
`error_type` and a sanitized `error_message`; upstream credential failures do not
invalidate the caller's local login. Model output, raw upstream errors, and usage
metadata are not returned.

Local authentication/permission failures retain HTTP `401`/`403`; missing and
disabled providers are rejected before the test with `404`/`409`. Invalid bodies
return `400`. Only `model_id` is accepted, so prompts, credentials, and unsaved
configuration cannot be supplied through this endpoint.

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

### Image Input

Image input uses the same `ContentPart` message shape for one-off chat,
context chat, sessions, and agent runs. Use a remote URL:

```json
{
  "type": "image",
  "url": "https://example.com/image.png",
  "detail": "high"
}
```

Or send raw base64 data with its MIME type:

```json
{
  "type": "image",
  "data": "iVBORw0KGgoAAA...",
  "mime_type": "image/png"
}
```

Do not set both `url` and `data`. OpenAI-compatible chat, OpenAI Responses,
and Anthropic accept URL images. All four built-in adapters accept base64
images; Gemini requires the base64 form because ordinary remote image URLs are
not valid Gemini inline image inputs. The web chat can select, preview, remove,
send, and display JPEG, PNG, WebP, and GIF images (up to four images and 5 MiB
per image). Declare `image_recognition` in a model's configured `capabilities`
to enable image attachment for that model. Declared models without the
capability reject image requests before a provider call is made.

## Provider-Specific Metadata

Provider-specific controls belong in request `metadata`, not in the core
`ChatRequest` fields. Unknown metadata stays inside EvernightAI and is not sent
to the provider.

OpenAI-compatible chat and OpenAI Responses adapters currently support:

- `reasoning_effort`: `"low"`, `"medium"`, or `"high"`

Responses maps this control to `reasoning.effort`; Chat Completions uses the
top-level `reasoning_effort` field. Neither adapter adds an output token limit
by default. Responses empty-output diagnostics include the upstream's
`max_output_tokens` when available; an unavailable limit remains `null`.

Responses function tools explicitly use `strict: false` to preserve optional
parameters and the registered JSON schemas. Tool argument validation and
permission checks still run locally before execution.

Anthropic and Gemini accept `metadata.max_output_tokens`, a positive integer.
The request value overrides the selected model's metadata, which overrides the
provider's metadata. Anthropic maps it to `max_tokens` and defaults to 4096;
Gemini maps it to `generationConfig.maxOutputTokens` and otherwise uses the
provider's default. Chat and streaming use the same precedence and validation.

Anthropic and Gemini preserve ordered assistant response blocks in message
metadata (`anthropic_content` / `gemini_parts`), including thinking signatures.
Return the complete assistant message in subsequent requests, or let the Agent
manage history. Editing visible text or tool calls without updating the preserved
blocks is rejected. Gemini recovers tool-result function names and native IDs
from the preceding assistant calls and groups adjacent tool results into one turn.

Streaming completion events may carry a complete `message`. The Agent saves
that message, including its metadata, across approval pauses and SQLite reloads.
Anthropic requires `message_stop`; Gemini requires `finishReason` and collects
remaining frames before completing. Stream errors, invalid JSON and premature
EOF fail the run instead of marking partial output complete.

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

## Skill Validation

`POST /skills/{skill_name}/render` validates `variables` against the registered
skill's optional `input_schema` before invoking its renderer. Direct Chat,
context Chat, Agent, and streaming calls use the same validation before calling
the model. Missing schemas impose no additional variable constraints.

The default schema dialect is Draft 2020-12. An explicit supported `$schema`
selects that draft. Validation does not convert types, insert `default` values,
or fetch external references. Local `$ref` definitions are supported. `format`
remains an annotation; no format checker is enabled.

Invalid variables return `SkillInputError` (HTTP `400`), whose string `detail`
contains a JSON object describing the first violation. For example:

```json
{
  "path": ["variables", "items", 0, "count"],
  "schema_path": ["properties", "items", "items", "properties", "count", "type"],
  "constraint": "type"
}
```

The diagnostic reports the parameter and schema location without echoing the
parameter value. A `required` violation points at the object containing the
missing property. Malformed schemas, unsupported drafts, and unresolved
references are `SkillConfigurationError`; malformed schemas are rejected during
registration before replacing an existing skill.

Renderers may raise `SkillInputError` for additional input rules; its type and
detail are preserved. Unexpected renderer exceptions and returned results whose
skill name or render ID do not match the request are `SkillRenderError` (HTTP
`502`). `output_schema` remains a declaration. Chat and Agent require every
`required_tools` name to appear in the request's available tool definitions
before the model call; they do not add tools or grant permissions automatically.

`POST /contexts/{context_id}/compose-preview` also validates skill variables. It
keeps the skill declarations in its returned request, without executing renderers
or calling a provider. Capability checks still occur when the request is used by
Chat or Agent; a context preview does not choose between these execution modes.

## Skill Templates

The skill management endpoints are:

| Method and path | Permission | Behavior |
| --- | --- | --- |
| `POST /skills` | `skills:create` | Create a template, HTTP 201 |
| `GET /skills/{name}/template` | `skills:get_template` | Read/export the template |
| `PATCH /skills/{name}` | `skills:update` | Edit or enable/disable a template |
| `DELETE /skills/{name}` | `skills:delete` | Delete a template, HTTP 204 |

Example creation/import payload:

```json
{
  "name": "style",
  "description": "Choose a response style",
  "prompt": "Use $tone style.",
  "is_enabled": true,
  "capabilities": ["chat", "agent"],
  "input_schema": {
    "type": "object",
    "properties": {"tone": {"type": "string", "enum": ["calm", "concise"]}},
    "required": ["tone"]
  },
  "required_tools": []
}
```

Templates produce a single system message. `$name` and `${name}` substitute
top-level variables; `$$` produces a literal dollar. Strings are inserted
literally, and other JSON values are serialized as JSON. Replacement text is not
interpreted again, and no code, file access, or model calls occur while rendering.
Missing placeholders produce `SkillInputError`. Invalid placeholder syntax is a
configuration error and cannot replace a working template.

Names are stable identifiers: start with an ASCII letter, followed by letters,
digits, `_`, `.`, or `-`, up to 128 characters. PATCH cannot rename a skill and
rejects unknown fields. Omitted fields are retained; `input_schema` and
`output_schema` may be explicitly cleared with null. Duplicate names, including
collisions with built-ins, return HTTP 409. Built-in callable skills are read-only
through these routes (HTTP 400).

Definitions include `is_enabled` and `is_template`. Disabled skills stay visible
to management but render/call attempts return `SkillDisabledError` (HTTP 409).
The SQLite bootstrap persists changes before publishing them to the runtime and
restores templates, including disabled ones, at startup. A storage failure leaves
the previous configuration active. Plain in-memory runtimes retain templates only
for their lifetime.

Template definitions/configurations also return an opaque `revision`, generated
by the server. Actual updates change it; empty or equivalent updates retain it.
PATCH cannot set `revision`. POST assigns a fresh revision even when an imported
configuration contains one. Deleting and recreating the same name also creates
a new revision. Existing stored templates without revisions are upgraded on
restore, and their assigned revisions remain stable across restarts.

The settings page imports JSON into its editor and saves only after explicit
submission. Exports use the same format. Common scalar parameters use form
controls; complex schemas keep the JSON editor. Model calls perform full server
validation. The chat selector includes only enabled Agent-capable skills and
shows required tools. Skill preview renders the saved skill without calling a
model; changing parameters or saved configuration clears previous results.

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

Preview the exact composed request without calling a provider:

```bash
curl -X POST http://127.0.0.1:8000/contexts/ctx-1/compose-preview \
  -H 'content-type: application/json' \
  -d '{
    "model_id": "gpt-4.1-mini",
    "messages": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "What would be sent?"}]
      }
    ],
    "memory_query": {
      "scope": "global",
      "text": "preference",
      "deduplicate": true
    }
  }'
```

The response is a `ChatRequest` containing the final messages, selected memory
ids, and context strategy metadata.

## Memories

Create a durable memory:

```bash
curl -X POST http://127.0.0.1:8000/memories \
  -H 'content-type: application/json' \
  -d '{
    "memory_id": "mem-style",
    "content": "Prefer concise answers",
    "kind": "preference",
    "scope": "global",
    "tags": ["style"],
    "priority": 10
  }'
```

Search and include disabled memories:

```bash
curl 'http://127.0.0.1:8000/memories?text=concise&tag=style&sort=priority&include_disabled=true'
```

Preview selection diagnostics:

```bash
curl -X POST http://127.0.0.1:8000/memories/select \
  -H 'content-type: application/json' \
  -d '{
    "text": "concise",
    "scopes": [
      {"scope": "context", "scope_id": "ctx-1"},
      {"scope": "global"}
    ],
    "deduplicate": true
  }'
```

Disable or re-enable a memory:

```bash
curl -X POST http://127.0.0.1:8000/memories/mem-style/disable
curl -X POST http://127.0.0.1:8000/memories/mem-style/enable
```

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

Agent run snapshots expose `usage` aggregated across completed model calls,
including calls before an approval or manual pause. `response.usage` remains
the usage of the latest model response. Each token field is summed only when
every completed call reports it; missing values remain `null`. Per-call usage,
including raw provider metadata, is retained in `usage.metadata.calls`.
Ordinary and streaming runs honor pause requests at the next safe checkpoint.
Text deltas preserve a pending pause request without interrupting the model
response halfway through. Provider error events and streams that end without a
completion signal fail the run instead of committing a successful response.
Responses streams also recover finalized text/refusal content from
`response.content_part.done` without duplicating deltas. Empty output failures
distinguish premature stream termination, incomplete responses and reasoning-only
output. The failed trace retains bounded event counts, response status and known
usage counts in `payload.error_detail`, without storing output text in diagnostics.
These failures do not automatically resend the request.

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
Tools emit `tool_started` before execution, followed by `tool_completed` or
`tool_failed`. Approval events precede execution for tools requiring consent.

With the managed run executor used by the SQLite runtime, closing a stream
connection does not cancel its run. Execution continues to persist its state
and trace, including pending approvals. Recover progress by reading
`GET /agent-runs/{run_id}` until the run stops or pauses; do not repeat the
start, resume, or retry POST merely because the connection dropped. Use
`POST /agent-runs/{run_id}/cancel` to stop execution explicitly. Timeouts and
shutdown recovery still apply.

Each persisted trace event has a 1-based `sequence` scoped to its run. Read a
trace incrementally with
`GET /agent-runs/{run_id}/trace?after_sequence=12&limit=100`; the response is
ordered and contains only events with a sequence greater than the cursor.

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

When HTTP authentication is enabled, browser clients should keep credentials out
of the URL and pass them as a WebSocket subprotocol token. The server reads the
token from `Sec-WebSocket-Protocol` and accepts only `evernight.realtime`, so the
secret is not echoed back as the negotiated protocol:

```javascript
const apiKey = "secret";
const encoded = btoa(apiKey).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const ws = new WebSocket("ws://127.0.0.1:8000/ws", [
  "evernight.realtime",
  `evernight.api_key.${encoded}`,
]);
```

Use `evernight.access_token.<base64url-token>` for OAuth bearer-style
credentials. Non-browser clients can continue to use
`Authorization: Bearer <token>` or `X-Evernight-API-Key: <api-key>` headers.
`/ws?api_key=...` and `/ws?access_token=...` remain accepted for compatibility,
but they can be exposed in access logs and browser tooling, so avoid them outside
controlled local debugging.

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
    "sequence": 1,
    "event_type": "run_started",
    "summary": "Agent run started",
    "metadata": {}
  },
  "payload": {"sequence": 1, "replayed": false},
  "metadata": {}
}
```

Each trace message includes replay metadata in `payload`:

- `sequence`: persisted 1-based trace sequence for the run
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
the connection subscribed to live trace messages for `run-1`. Replay and live
broadcasts share the same per-connection subscription cursor, so an event
persisted during reconnect is delivered once in sequence order.

After replay finishes, the server sends a correlated `agent_run.subscribed`
client event. Its `sequence` is the final server cursor, so clients can treat
that message as the boundary between reconnect replay and live delivery.

```json
{
  "message_type": "client_event",
  "correlation_id": "subscribe-1",
  "run_id": "run-1",
  "client_event": {
    "event_name": "agent_run.subscribed",
    "payload": {"run_id": "run-1", "sequence": 3},
    "metadata": {}
  },
  "payload": {},
  "metadata": {}
}
```

Stop live delivery with `agent_run.unsubscribe`. The server responds with a
correlated `agent_run.unsubscribed` client event after the subscription has
been removed; no later trace broadcast for that subscription is sent after the
acknowledgement.

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

Agent state exposes `skill_revisions`, captured when execution starts. Resuming
requires each selected skill to exist, remain enabled, and match that revision.
A changed/recreated template returns `SkillConflictError` (HTTP 409), a disabled
skill returns `SkillDisabledError` (HTTP 409), and a deleted skill returns
`SkillNotFoundError` (HTTP 404). Rejected resumes leave the paused snapshot,
pending approvals, completed tools, and context unchanged. Cancel the old run
and start a new one to use updated configuration; new runs require fresh
approval decisions for sensitive actions.

The same checks run before each tool execution and model dispatch, including
streaming. Changes during an active run stop its next action and record a failed
state with its trace and completed tool executions; the unfinished transcript is
not appended to context. A call already in flight may complete. Legacy paused
runs with skills but no recorded revisions are rejected with HTTP 409; runs
without skills remain resumable.

Retry a failed, canceled, or unrecoverable paused run as SSE with a
caller-known new run id:

```bash
curl -N -X POST http://127.0.0.1:8000/agent-runs/run-1/retry/stream \
  -H 'content-type: application/json' \
  -d '{"retried_run_id": "run-retry-1"}'
```

The retry state is persisted before the SSE response starts. A client may
therefore cancel it immediately with
`POST /agent-runs/run-retry-1/cancel`, including after the stream disconnects.

### Current authentication identity

`GET /auth/me` validates the request credential using the configured authentication
adapters. It returns `authentication_enabled` and a `principal` containing only
`principal_id`, `principal_type`, `roles`, and `permissions`. No resource permission
is required to inspect one's own identity. Invalid or missing credentials return
401 when authentication is enabled. With authentication disabled, `principal` is
null. Identity responses and authentication/permission errors use `Cache-Control:
no-store`.

The browser validates API keys or Bearer tokens before saving them. Signing out
removes browser credentials and disables page-provided fallback credentials for
that browser until another credential is saved. This does not revoke a static API
key or an externally issued token on the server. Identity changes clear the chat
view and workspace data and disconnect settings trace subscriptions. Authorization
adapters must implement the scope-aware protocols: a failing scoped call is never
retried without its ownership scope.

### Displaying generated files

When filesystem tools are enabled, the built-in `display_file` tool can publish
an existing file from the current working directory:

```json
{"path":"plots/chart.png","title":"Sales chart","filename":"sales.png"}
```

Create the file first using a shell or project tool, then call `display_file`.
For example, a matplotlib script can save `plots/chart.png` using `savefig` before
the model displays it. The tool accepts relative paths, absolute paths within the
selected directory, and `/workspace/` paths returned by sandbox tools. Files
outside the selected directory, escaping symlinks, directories, and special
files are rejected. Each file is limited to 20 MiB. Normal tool policies and
approvals also apply.

The tool saves an immutable snapshot in SQLite and returns metadata with
`type: "file_display"` and an `artifact_id`. Binary content and Base64 are not
included in model-visible tool results. The chat shows PNG, JPEG, GIF and WebP
previews, interactive HTML previews, and a download button. Other formats,
including SVG and PDF, are downloadable. The snapshot remains available after
the source file is changed or deleted and after service restarts. Saved agent
traces restore the card on reload.

For an HTML visualization, create `chart.html` and call
`display_file` with `{"path":"chart.html","title":"Interactive chart"}`.
New HTML snapshots have `preview_kind: "html"`; older HTML snapshots also preview
based on their `text/html` MIME type. The browser loads the saved content into an
iframe with `sandbox="allow-scripts"`, without same-origin, popup, top-navigation,
form or download permissions. Inline CSS and JavaScript, canvas/SVG charts, and
absolute HTTPS script, stylesheet, image, font and media resources are supported.
The preview cannot read the chat DOM, login credentials or browser storage.
Network data requests, nested frames, objects and form submissions are blocked.
Embed data and local assets in the HTML: relative companion files are not
published by this single-file tool. The preview uses UTF-8. Downloads retain the
original bytes, without the preview's injected content policy.

`GET /files/{artifact_id}` returns file metadata and requires `files:get`.
`GET /files/{artifact_id}/content` returns binary content and requires
`files:read`. Add `?download=true` to force a download. Authenticated users can
only read their own artifacts; anonymous local access follows the shared runtime
scope. Active formats are always served as downloads with `nosniff` and a sandbox
content policy. The frontend fetches files with the configured API key or bearer
token and uses temporary Blob URLs for previews, clearing them on sign-out or an
identity change. HTML runs only inside the isolated frontend preview; the content
endpoint continues to serve it as an attachment. Do not place credentials or
backend filesystem paths in preview URLs.

### Working folders

Configure the default tool directory in `config.toml`:

```toml
[tools.filesystem]
enabled = true
root = "/srv/evernight/workspaces"
```

Create this directory before starting the service. Absolute paths avoid dependence
on the startup directory; `root = "."` means the process working directory, not
necessarily the directory containing `config.toml`. Tools use this directory when
no project is selected. The sidebar browser reaches the backend user's home
directory on Linux and the current drive root on Windows, independently of this
default. Restart the backend after changing the configuration.

Start with `evernight-http --config config.toml` to load this configuration.
The direct `uvicorn EvernightAI.bootstrap.http:create_app --factory` entry instead
uses environment variables, including `EVERNIGHTAI_FILESYSTEM_ROOT`; it does not
read `config.toml`.

With filesystem tools enabled, `GET /workspaces?path=.` lists up to 500 entries
inside the home directory or drive root. Listings return absolute paths and a
`parent` path until that boundary is reached. On Windows, opening an absolute path
on another drive uses that drive's root. Relative paths other than `.` remain
relative to the configured tool directory for compatibility.
`POST /workspaces` with `{"path":".","name":"demo"}`
creates a child directory. Authentication requires `workspaces:list` or
`workspaces:create` respectively (or `*`). The browsing directory is shared
by principals granted these permissions; these are not private per-user folders.
Paths containing `..` and symlinks escaping the browsing boundary are rejected.
Registered projects outside the home directory keep their own browsing boundary.

`GET /workspaces/projects` lists the default root and added projects. Register an
existing directory on the backend host with `POST /workspaces/projects` and
`{"path":"/home/user/projects/example"}`. Registration requires
`workspaces:register` (or `*`), validates the real directory, and persists it in
SQLite. Projects are shared by principals with workspace access. Service data,
credentials and configured runtime directories cannot be registered as projects.
The API returns the opened directory; it does not copy or relocate project files.

Browsing a directory does not grant tool access to it. A listing with
`requires_registration: true` is registered when the user chooses it in the sidebar,
using the same registration permission and protected-directory checks.

The chat sidebar provides project registration, browsing, folder creation, and selection. Selection is
stored in this browser, validated on reload, and cleared on authentication changes.
`AgentRunRequest.working_directory` (also accepted by session agent requests) stores
the selected directory on each run: a relative path within the default root, or an
absolute path within an added project. Filesystem, Shell, Git and project tasks
resolve the same selection per call, including resumed runs and approval previews.
Changing the sidebar selection affects subsequent requests only. With no selection,
each tool retains its configured default. A selected directory cannot be combined
with a tool's named `project` argument. Model-supplied `_working_directory` values
are discarded; only the request's execution context supplies the selection.
Shell `cwd` remains bounded to the selected project. Bubblewrap mounts only that
project at `/workspace`; registration does not expose other projects or service data.


### Tool policy management

`GET /tools` returns the current principal's available tools. Manage all registered
tools, including forbidden tools, using `GET /tools/policies`. Save a per-tool mode
with `PUT /tools/{tool_name}/policy` and `{ "mode": "allow" }`, `"ask"`, or `"deny"`.
Use `DELETE /tools/{tool_name}/policy` to restore defaults. Reading requires
`tools:list`; mutation requires `tools:configure`. Policies persist in SQLite and
remain subject to server execution restrictions. See [tool permissions](tool-permissions.md).
