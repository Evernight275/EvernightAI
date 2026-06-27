# EvernightAI Architecture Diagrams

This document contains six focused diagrams. Each diagram answers one question
and uses labeled arrows so the dependency or runtime relationship is explicit.

## 1. Source Dependency

Question: which package layers import which other package layers?

This is an import graph, not a runtime call graph.

```mermaid
flowchart TD
    Compat["compat shims<br/>EvernightAI.cli<br/>EvernightAI.server"]
    Entrypoint["entrypoint<br/>process/command launchers"]
    Bootstrap["bootstrap<br/>composition root"]
    Interface["interface<br/>HTTP + CLI boundary"]
    Application["application<br/>use-case services"]
    Infra["infra<br/>concrete adapters + registrations"]
    Core["core<br/>domain + schema + protocol + error"]

    Compat -- "imports" --> Entrypoint

    Entrypoint -- "loads config / starts process" --> Bootstrap
    Entrypoint -- "uses CLI command helpers" --> Interface
    Entrypoint -- "raises/handles core errors" --> Core

    Bootstrap -- "assembles apps" --> Application
    Bootstrap -- "assembles adapters/stores" --> Infra
    Bootstrap -- "builds HTTP/CLI-facing objects" --> Interface
    Bootstrap -- "constructs runtime/domain objects" --> Core

    Interface -- "depends on schemas/protocols/errors" --> Core
    Application -- "coordinates through protocols/schemas" --> Core
    Infra -- "implements core protocols" --> Core

    Application -. "does not import" .-> Infra
    Interface -. "does not import" .-> Application
    Interface -. "does not import" .-> Infra
    Core -. "does not import outward" .-> Application
```

Key point: `bootstrap` is the only normal layer that imports across all roles.
The inner operational layers converge on `core`.

## 2. Runtime Assembly

Question: what does `bootstrap.runtime` actually put into `RuntimeKernel`?

```mermaid
flowchart TD
    Config["EvernightConfig<br/>config.toml + environment"]
    RuntimeFactory["bootstrap.config<br/>create_runtime_from_config"]
    SQLiteRuntime["bootstrap.runtime<br/>create_sqlite_runtime"]

    Runtime["RuntimeKernel"]

    subgraph ProviderSide["provider side"]
        ProviderFactory["ProviderFactory"]
        ProviderManager["ProviderManager"]
        ProviderRegs["infra provider registrations<br/>openai / responses / gemini / anthropic"]
    end

    subgraph ToolSide["tool side"]
        ToolRegister["ToolRegister"]
        ToolManager["ToolManager"]
        ToolPolicy["BasicToolSafetyPolicy"]
        ToolRegs["infra tool registrations<br/>filesystem / shell / web / git / project / runtime_data"]
    end

    subgraph SkillSide["skill side"]
        SkillRegister["SkillRegister"]
        SkillManager["SkillManager"]
        EchoSkill["echo skill registration"]
    end

    subgraph StateSide["runtime state side"]
        ContextManager["ContextManager"]
        ContextStrategy["ContextOrganizer<br/>BasicContextStrategy"]
        MemoryManager["MemoryManager"]
        MemoryStrategy["BasicMemoryStrategy<br/>BasicMemoryWriteStrategy"]
        SessionManager["SessionManager"]
        AgentStores["Agent run state + trace registers"]
        SQLiteStores["SQLite adapters<br/>context / memory / session / agent"]
    end

    Config -- "tool/provider/db options" --> RuntimeFactory
    RuntimeFactory -- "delegates concrete assembly" --> SQLiteRuntime
    SQLiteRuntime -- "returns" --> Runtime

    SQLiteRuntime -- "registers provider builders" --> ProviderRegs
    ProviderRegs -- "builder functions" --> ProviderFactory
    ProviderFactory -- "owned by" --> Runtime
    ProviderManager -- "uses" --> ProviderFactory
    Runtime -- "owns" --> ProviderManager

    SQLiteRuntime -- "registers enabled tools" --> ToolRegs
    ToolRegs -- "tool definitions + executors" --> ToolRegister
    ToolRegister -- "owned by" --> Runtime
    ToolManager -- "uses" --> ToolRegister
    ToolManager -- "checks" --> ToolPolicy
    Runtime -- "owns" --> ToolManager

    SQLiteRuntime -- "registers builtin skills" --> EchoSkill
    EchoSkill --> SkillRegister
    SkillRegister -- "owned by" --> Runtime
    SkillManager -- "uses" --> SkillRegister
    Runtime -- "owns" --> SkillManager

    SQLiteRuntime -- "creates" --> SQLiteStores
    SQLiteStores -- "back" --> ContextManager
    SQLiteStores -- "back" --> MemoryManager
    SQLiteStores -- "back" --> SessionManager
    SQLiteStores -- "back" --> AgentStores
    Runtime -- "owns" --> ContextManager
    Runtime -- "owns" --> ContextStrategy
    Runtime -- "owns" --> MemoryManager
    Runtime -- "owns" --> MemoryStrategy
    Runtime -- "owns" --> SessionManager
    Runtime -- "owns" --> AgentStores
```

Key point: registrations provide builders/executors into core registries; the
runtime owns the resulting managers and strategies.

## 3. Request Call Chain

Question: what happens when a chat or agent request enters through HTTP or CLI?

```mermaid
sequenceDiagram
    participant Client as Client
    participant Route as HTTP route / CLI command
    participant Auth as Optional AuthorizedEvernightInterface
    participant Interface as EvernightInterface
    participant App as ChatApplication / AgentApplication
    participant Runtime as RuntimeKernel
    participant Stores as Context/Memory/Session stores
    participant Skills as SkillManager
    participant Providers as ProviderManager
    participant Adapter as Provider adapter
    participant LLM as External model API
    participant Tools as ToolManager
    participant ToolAdapter as Tool adapter

    Client->>Route: request payload / CLI args
    Route->>Auth: call interface protocol
    Auth->>Auth: permission check if auth enabled
    Auth->>Interface: forward allowed call
    Interface->>App: invoke application use case

    App->>Runtime: access managers
    App->>Stores: load context/session/memory
    App->>Skills: render requested skills into prompt messages
    App->>Providers: resolve provider instance
    Providers->>Adapter: chat or chat_stream
    Adapter->>LLM: provider-specific API call
    LLM-->>Adapter: provider-specific response
    Adapter-->>Providers: normalized core response/events

    opt model emits tool call
        App->>Tools: execute ToolCall
        Tools->>Tools: policy + approval check
        Tools->>ToolAdapter: execute dict arguments
        ToolAdapter-->>Tools: dict result
        Tools-->>App: ToolCallResult
    end

    App->>Stores: persist updated context/memory/session/agent trace
    App-->>Interface: core result schema
    Interface-->>Route: result
    Route-->>Client: HTTP response / CLI output
```

Key point: HTTP and CLI translate transport details into interface calls; the
application layer coordinates the use case through runtime managers.

## 4. Data Flow

Question: where do request data, context, memory, skills, tools, provider
responses, and persistence meet?

```mermaid
flowchart TD
    Input["incoming input<br/>HTTP JSON / CLI args"]
    RequestSchema["core request schema<br/>ChatRequest / AgentRunRequest / Session*"]

    ContextStore["context store<br/>SQLite or in-memory register"]
    MemoryStore["memory store<br/>SQLite or in-memory register"]
    SessionStore["session store<br/>SQLite or in-memory register"]
    AgentStore["agent state + trace store<br/>SQLite register"]

    ContextWindow["context window<br/>stored messages + request messages"]
    MemorySelection["memory selection<br/>durable facts/summaries"]
    SkillMessages["skill-rendered prompt messages"]
    ToolDefinitions["registered tool definitions"]

    ProviderPayload["provider adapter payload"]
    ProviderResponse["provider response"]
    CoreResult["core result schema<br/>ChatResponse / AgentRunResult / stream events"]
    ToolResults["ToolCallResult"]

    Input -- "validated into" --> RequestSchema

    RequestSchema -- "context_id/session_id" --> ContextStore
    RequestSchema -- "memory query" --> MemoryStore
    RequestSchema -- "session request" --> SessionStore

    ContextStore -- "messages" --> ContextWindow
    MemoryStore -- "selected memories" --> MemorySelection
    MemorySelection -- "system memory message" --> ContextWindow
    RequestSchema -- "skill declarations" --> SkillMessages
    SkillMessages --> ContextWindow
    RequestSchema -- "tool declarations" --> ToolDefinitions

    ContextWindow -- "messages" --> ProviderPayload
    ToolDefinitions -- "available tools" --> ProviderPayload
    ProviderPayload --> ProviderResponse
    ProviderResponse -- "mapped by adapter" --> CoreResult

    ProviderResponse -- "tool calls" --> ToolResults
    ToolResults -- "fed back into agent loop" --> ContextWindow

    CoreResult -- "append response / traces" --> ContextStore
    CoreResult -- "write summaries when enabled" --> MemoryStore
    CoreResult -- "update session result" --> SessionStore
    CoreResult -- "persist run state/trace" --> AgentStore
```

Key point: context and memory are separate. Memory selects durable information;
context organizes the model-visible window.

## 5. Permission Boundary

Question: where are user/API permissions and tool-execution permissions checked?

```mermaid
flowchart TD
    HTTPClient["HTTP client"]
    CLIUser["CLI user"]

    HTTPAuth["interface.http.auth<br/>API key / OAuth JWT"]
    CLIAuth["interface.cli.auth<br/>config principal / env key"]
    Principal["Principal<br/>roles + permissions"]
    Authorizer["core.domain.auth<br/>Authorizer + PermissionAuthPolicy"]
    AuthorizedInterface["AuthorizedEvernightInterface"]
    Interface["EvernightInterface"]

    App["Application service"]
    ToolCall["ToolCall"]
    ToolDefinition["ToolDefinition<br/>permissions + safety level"]
    ToolPolicy["BasicToolSafetyPolicy"]
    Approval["ToolApprovalDecision<br/>or metadata.approved"]
    Executor["Tool executor"]

    SafeTarget["safe/read target"]
    SensitiveTarget["sensitive target<br/>write / process / network / database / external_api"]
    BlockedTarget["blocked target<br/>shell / destructive by default"]

    HTTPClient -- "Authorization / X-Evernight-API-Key" --> HTTPAuth
    CLIUser -- "configured CLI principal" --> CLIAuth
    HTTPAuth --> Principal
    CLIAuth --> Principal
    Principal --> Authorizer
    Authorizer -- "allows interface permission" --> AuthorizedInterface
    AuthorizedInterface --> Interface
    Interface --> App

    App -- "model requested tool" --> ToolCall
    ToolCall --> ToolDefinition
    ToolDefinition --> ToolPolicy

    ToolPolicy -- "safe permission" --> Executor
    ToolPolicy -- "requires approval" --> Approval
    Approval -- "approved" --> Executor
    ToolPolicy -. "rejects" .-> BlockedTarget

    Executor --> SafeTarget
    Executor --> SensitiveTarget
```

Key point: interface authorization controls who may call EvernightAI operations;
tool safety controls whether a specific tool execution may touch sensitive
targets.

## 6. Deployment Relationship

Question: what runs as processes, and what external systems do those processes
talk to?

```mermaid
flowchart TD
    Operator["operator / developer"]
    Config["config.toml"]
    Env["environment variables<br/>provider keys / auth / paths"]

    subgraph LocalMachine["local machine / server"]
        CLIProcess["evernight<br/>CLI process"]
        HTTPProcess["evernight-http / uvicorn<br/>HTTP process"]
        StaticUI["frontend/dist<br/>optional static UI"]
        Runtime["RuntimeKernel<br/>in process"]
        SQLite["runtime SQLite database<br/>.evernight/runtime.sqlite3 or configured path"]
        FSRoot["configured filesystem root"]
        GitRepo["configured git repository"]
        ProjectRoot["configured project working directory"]
    end

    subgraph External["external systems"]
        Providers["LLM provider APIs<br/>OpenAI-compatible / Responses / Gemini / Anthropic"]
        WebTargets["web targets<br/>HTTP request / scrape / download"]
        ShellCommands["allowlisted local commands"]
    end

    Operator -- "writes" --> Config
    Operator -- "exports" --> Env
    Config -- "read by" --> CLIProcess
    Config -- "read by" --> HTTPProcess
    Env -- "read by" --> CLIProcess
    Env -- "read by" --> HTTPProcess

    CLIProcess -- "creates interface/runtime" --> Runtime
    HTTPProcess -- "create_app factory" --> Runtime
    HTTPProcess -- "serves if configured" --> StaticUI

    Runtime -- "persists" --> SQLite
    Runtime -- "provider adapters call" --> Providers
    Runtime -- "web tools call" --> WebTargets
    Runtime -- "filesystem tools constrain access to" --> FSRoot
    Runtime -- "git tools constrain access to" --> GitRepo
    Runtime -- "project task tool runs allowlisted commands in" --> ProjectRoot
    Runtime -- "shell tool runs allowlisted commands" --> ShellCommands
```

Key point: EvernightAI has no separate worker process in the current design.
HTTP and CLI each assemble an in-process runtime from config; SQLite and
external provider/tool targets sit outside the runtime boundary.
