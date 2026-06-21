# AGENTS.md

This file is the collaboration guide for AI agents working on EvernightAI.
Read it before changing code.

## Project Shape

EvernightAI is a Python 3.12 package with a layered architecture:

```text
src/EvernightAI/core        domain models, schemas, protocols, errors
src/EvernightAI/application thin application services
src/EvernightAI/infra       concrete adapters and bootstrap wiring
src/EvernightAI/interface   external communication boundaries
tests                       unit, architecture, and opt-in real-flow tests
```

The current closed loop is:

```text
RuntimeKernel -> ChatApplication -> ProviderManager -> OpenAI-compatible adapter
-> real provider -> response mapper -> ChatResponse
```

## Non-Negotiable Rules

- Keep `core` independent from `application` and `infra`.
- Keep `application` independent from `infra`.
- Keep `interface` independent from `application` and `infra`.
- Keep package `__init__.py` files comment-only.
- Do not require OpenAI-compatible providers to support remote `/models`.
- Do not require `ProviderConfig.model` to contain a model before `chat` or
  `chat_stream` can call it.
- Keep context storage as a core protocol/domain concern only; database and ORM
  integrations belong in infra adapters.
- Keep memory separate from context. Memory selects durable facts,
  preferences, summaries, definitions, and episodic information; context
  organizes the current model-visible window.
- Use `ProviderFactory` / `ProviderFactoryProtocol` as the provider creation
  boundary. Infra registration code supplies builders to that factory; concrete
  adapter instances expose runtime behavior and should not own the higher-level
  assembly flow.
- Use `EvernightInterfaceProtocol` as the interface boundary. HTTP and CLI
  layers receive an already assembled interface/runtime and must not create
  application services, SQLite, in-memory, or other infra-backed runtimes
  themselves.
- Keep real provider tests opt-in and skipped by default.
- Treat real provider unavailability as `pytest.skip`, not as a failed local
  integration test.
- Preserve clear skip reasons in pytest output.
- Prefer focused tests that lock behavior over broad incidental assertions.

These rules are backed by tests. If a change needs to break one, update the rule
and the tests deliberately.

## Common Commands

Run the normal test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run type checking:

```powershell
.\.venv\Scripts\pyright.exe
```

Start the local HTTP interface:

```powershell
$env:EVERNIGHTAI_DATABASE_PATH=".evernight\runtime.sqlite3"
$env:EVERNIGHTAI_FILESYSTEM_ROOT=(Get-Location).Path
.\.venv\Scripts\python.exe -m uvicorn EvernightAI.entrypoint.server:create_app --factory --reload
```

The HTTP startup module is a package-level composition root. Keep runtime and
service assembly there or in application/infra bootstrap code, not in
`interface/http`.

Run the real OpenAI-compatible smoke test:

```powershell
$env:EVERNIGHTAI_RUN_REAL_OPENAI="1"
$env:EVERNIGHTAI_REAL_OPENAI_API_KEY="your-key"
$env:EVERNIGHTAI_REAL_OPENAI_MODEL="deepseek-chat"
$env:EVERNIGHTAI_REAL_OPENAI_BASE_URL="https://your-openai-compatible-endpoint/v1"
.\.venv\Scripts\python.exe -m pytest tests\test_real_openai_flow.py -m real_openai
```

`EVERNIGHTAI_REAL_OPENAI_BASE_URL` can be omitted for the default OpenAI API.
`OPENAI_API_KEY` and `OPENAI_BASE_URL` are supported as fallbacks.

Run the real OpenAI Responses smoke test:

```powershell
$env:EVERNIGHTAI_RUN_REAL_OPENAI_RESPONSES="1"
$env:EVERNIGHTAI_REAL_OPENAI_RESPONSES_API_KEY="your-key"
$env:EVERNIGHTAI_REAL_OPENAI_RESPONSES_MODEL="gpt-4.1-mini"
.\.venv\Scripts\python.exe -m pytest tests\test_real_openai_responses_flow.py -m real_openai_responses
```

`EVERNIGHTAI_REAL_OPENAI_RESPONSES_BASE_URL` can be omitted for the default
OpenAI API. `OPENAI_API_KEY` and `OPENAI_BASE_URL` are supported as fallbacks.

Run the real Gemini smoke test:

```powershell
$env:EVERNIGHTAI_RUN_REAL_GEMINI="1"
$env:EVERNIGHTAI_REAL_GEMINI_API_KEY="your-key"
$env:EVERNIGHTAI_REAL_GEMINI_MODEL="gemini-2.0-flash"
.\.venv\Scripts\python.exe -m pytest tests\test_real_gemini_flow.py -m real_gemini
```

`EVERNIGHTAI_REAL_GEMINI_BASE_URL` can be omitted for the default Gemini API.
`GOOGLE_API_KEY` is supported as a fallback.

Run the real Anthropic smoke test:

```powershell
$env:EVERNIGHTAI_RUN_REAL_ANTHROPIC="1"
$env:EVERNIGHTAI_REAL_ANTHROPIC_API_KEY="your-key"
$env:EVERNIGHTAI_REAL_ANTHROPIC_MODEL="claude-3-5-haiku-latest"
.\.venv\Scripts\python.exe -m pytest tests\test_real_anthropic_flow.py -m real_anthropic
```

`EVERNIGHTAI_REAL_ANTHROPIC_BASE_URL` can be omitted for the default Anthropic
API. `ANTHROPIC_API_KEY` is supported as a fallback.

## Test Expectations

Before finishing code changes, run:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\pyright.exe
```

If you touch OpenAI-compatible adapter behavior, make sure these cases remain
covered:

- declared model chat
- undeclared model chat
- declared model stream
- undeclared model stream
- OpenAI SDK errors translated into EvernightAI provider errors
- real provider unavailable path skips with a useful reason

Do not run real provider tests unless the user asks or the needed environment
variables are already intentionally set for that purpose.

## Design Notes

- `ProviderConfig.model` is a local declaration/capability registry. It is not a
  required discovery result from the remote service.
- `chat` and `chat_stream` should pass `ChatRequest.model_id` through to the
  provider even when it is not predeclared.
- `list_models`, `get_model`, and `supports` may rely on local declared models.
- Adapter errors should preserve the provider's useful detail while translating
  into EvernightAI domain errors.
- Keep `application` thin. It should coordinate through protocols and runtime,
  not know concrete infra classes.
- Keep `interface` as an external communication boundary. It may depend on
  core protocols/schemas and transport frameworks, but application service and
  concrete runtime assembly belong outside interface.
- Context protocols define behavior and data shape. They should not import ORM,
  database clients, or persistence frameworks.
- Basic context organization means preserving stored context messages first and
  appending current request messages after them. It should not perform retrieval,
  summarization, token trimming, or memory policy decisions.
- Memory strategy should select memory candidates only. Application code is
  responsible for explicitly composing selected memories into a context window
  or chat request.

## Editing Style

- Match the existing small, explicit style.
- Keep comments rare and useful.
- Prefer adding or adjusting a targeted test with behavior changes.
- Avoid unrelated refactors while fixing a narrow behavior.
- Do not commit secrets, `.env` files, coverage files, caches, or virtualenv
  content.
