# EvernightAI Architecture Diagrams

This document captures six architecture views of the current EvernightAI codebase.

## 1. Source Dependency

```mermaid
flowchart TD
    subgraph Compat["compat modules"]
        CCLI["EvernightAI.cli"]
        CSRV["EvernightAI.server"]
    end

    subgraph Entrypoint["entrypoint"]
        ECLI["entrypoint.cli"]
        ESRV["entrypoint.server"]
    end

    subgraph Bootstrap["bootstrap"]
        BCFG["bootstrap.config"]
        BRT["bootstrap.runtime"]
        BIF["bootstrap.interface"]
        BHTTP["bootstrap.http"]
    end

    subgraph Interface["interface"]
        ICLI["interface.cli"]
        IHTTP["interface.http"]
        ILOG["interface.log_store"]
    end

    subgraph Application["application"]
        ACHAT["chat"]
        AAGENT["agent"]
        APROV["provider"]
        ATOOL["tool"]
        ASESS["session"]
        ASKILL["skill"]
    end

    subgraph Infra["infra"]
        IREG["registrations"]
        IADP["adapters"]
    end

    subgraph Core["core"]
        CDOM["domain"]
        CPRO["protocol"]
        CSCH["schema"]
        CERR["error"]
    end

    CCLI --> ECLI
    CSRV --> ESRV

    ECLI --> BCFG
    ECLI --> ICLI
    ECLI --> CERR
    ESRV --> BHTTP

    BCFG --> BRT
    BCFG --> BIF
    BCFG --> ICLI
    BRT --> CDOM
    BRT --> CPRO
    BRT --> IREG
    BRT --> IADP
    BIF --> ACHAT
    BIF --> AAGENT
    BIF --> APROV
    BIF --> ATOOL
    BIF --> ASESS
    BIF --> ASKILL
    BIF --> CDOM
    BHTTP --> IHTTP

    ICLI --> CPRO
    ICLI --> CSCH
    IHTTP --> CPRO
    IHTTP --> CSCH
    IHTTP --> CERR
    ILOG --> CSCH

    ACHAT --> CPRO
    ACHAT --> CSCH
    AAGENT --> CPRO
    AAGENT --> CSCH
    APROV --> CPRO
    APROV --> CSCH
    ATOOL --> CPRO
    ASESS --> CPRO
    ASESS --> CSCH
    ASKILL --> CPRO
    ASKILL --> CSCH

    IREG --> CPRO
    IREG --> CSCH
    IADP --> CPRO
    IADP --> CSCH
    IADP --> CERR

    CDOM --> CPRO
    CDOM --> CSCH
    CDOM --> CERR
    CPRO --> CSCH
    CERR --> CSCH
```

## 2. Runtime Assembly

```mermaid
flowchart TD
    Config["EvernightConfig<br/>config.toml + env"]
    CreateRuntime["bootstrap.config<br/>create_runtime_from_config"]
    RuntimeAssembly["bootstrap.runtime<br/>create_sqlite_runtime"]
    InterfaceAssembly["bootstrap.interface<br/>create_interface"]
    HTTPAssembly["bootstrap.http<br/>create_app_from_config"]

    Runtime["RuntimeKernel"]

    ProviderFactory["ProviderFactory"]
    ProviderManager["ProviderManager"]
    ToolRegister["ToolRegister"]
    ToolManager["ToolManager"]
    ToolPolicy["BasicToolSafetyPolicy"]
    SkillRegister["SkillRegister"]
    SkillManager["SkillManager"]
    ContextManager["ContextManager"]
    ContextStrategy["ContextOrganizer + BasicContextStrategy"]
    MemoryManager["MemoryManager"]
    MemoryStrategy["BasicMemoryStrategy + BasicMemoryWriteStrategy"]
    SessionManager["SessionManager"]
    AgentState["Agent run state register"]
    AgentTrace["Agent trace register"]

    ProviderRegs["provider registrations<br/>openai / responses / gemini / anthropic"]
    ToolRegs["tool registrations<br/>filesystem / shell / web / git / project / runtime_data"]
    SkillRegs["skill registrations<br/>echo"]
    SQLiteRegs["SQLite registers<br/>context / memory / session / agent"]

    Interface["EvernightInterface"]
    Authorized["AuthorizedEvernightInterface<br/>optional auth wrapper"]
    HTTPApp["FastAPI app"]

    Config --> CreateRuntime
    Config --> HTTPAssembly
    CreateRuntime --> RuntimeAssembly
    RuntimeAssembly --> Runtime
    RuntimeAssembly --> ProviderRegs
    RuntimeAssembly --> ToolRegs
    RuntimeAssembly --> SkillRegs
    RuntimeAssembly --> SQLiteRegs

    Runtime --> ProviderFactory
    Runtime --> ProviderManager
    Runtime --> ToolRegister
    Runtime --> ToolManager
    Runtime --> ToolPolicy
    Runtime --> SkillRegister
    Runtime --> SkillManager
    Runtime --> ContextManager
    Runtime --> ContextStrategy
    Runtime --> MemoryManager
    Runtime --> MemoryStrategy
    Runtime --> SessionManager
    Runtime --> AgentState
    Runtime --> AgentTrace

    ProviderRegs --> ProviderFactory
    ToolRegs --> ToolRegister
    SkillRegs --> SkillRegister
    SQLiteRegs --> ContextManager
    SQLiteRegs --> MemoryManager
    SQLiteRegs --> SessionManager
    SQLiteRegs --> AgentState
    SQLiteRegs --> AgentTrace

    Runtime --> InterfaceAssembly
    InterfaceAssembly --> Interface
    InterfaceAssembly --> Authorized
    HTTPAssembly --> HTTPApp
    HTTPApp --> Interface
```

## 3. Request Call Chain

```mermaid
sequenceDiagram
    participant Client as HTTP / CLI Client
    participant Boundary as interface.http / interface.cli
    participant Auth as Auth wrapper
    participant EI as EvernightInterface
    participant App as Application service
    participant Runtime as RuntimeKernel
    participant Store as Context / Memory / Session stores
    participant ProviderMgr as ProviderManager
    participant Adapter as Provider adapter
    participant ToolMgr as ToolManager
    participant Tool as Tool adapter
    participant LLM as External provider

    Client->>Boundary: request payload
    Boundary->>Auth: optional authorization
    Auth->>EI: protocol call
    EI->>App: use-case method
    App->>Runtime: coordinate managers

    App->>Store: load context / memory / session
    App->>ProviderMgr: resolve provider instance
    ProviderMgr->>Adapter: chat / chat_stream
    Adapter->>LLM: provider API request
    LLM-->>Adapter: provider response / stream chunks
    Adapter-->>ProviderMgr: normalized ChatResponse / ChatStreamEvent

    opt model requests tool execution
        App->>ToolMgr: execute ToolCall
        ToolMgr->>ToolMgr: safety policy / approval decision
        ToolMgr->>Tool: execute arguments
        Tool-->>ToolMgr: dict result
        ToolMgr-->>App: ToolCallResult
    end

    App->>Store: persist context / memory / session / agent trace
    App-->>EI: result schema
    EI-->>Boundary: result
    Boundary-->>Client: HTTP / CLI response
```

## 4. Data Flow

```mermaid
flowchart LR
    Request["Incoming request<br/>HTTP body / CLI args"]
    CoreSchema["core.schema<br/>ChatRequest / AgentRunRequest / ToolCall / Session*"]
    Context["Context<br/>current visible window"]
    Memory["Memory<br/>durable facts and summaries"]
    Skills["Skills<br/>prompt render messages"]
    Tools["Tools<br/>ToolDefinition + ToolCall"]
    ProviderPayload["Provider adapter payload"]
    ProviderResponse["Provider response"]
    Normalized["core.schema result<br/>ChatResponse / stream events / ToolCallResult"]
    Stores["SQLite stores<br/>contexts / memories / sessions / agent runs"]

    Request --> CoreSchema
    CoreSchema --> Context
    CoreSchema --> Memory
    CoreSchema --> Skills
    CoreSchema --> Tools

    Memory --> Context
    Skills --> Context
    Context --> ProviderPayload
    Tools --> ProviderPayload

    ProviderPayload --> ProviderResponse
    ProviderResponse --> Normalized

    Normalized --> Stores
    Context --> Stores
    Memory --> Stores
    Stores --> Context
    Stores --> Memory
```

## 5. Permission Boundary

```mermaid
flowchart TD
    User["Caller"]
    HTTPAuth["HTTP auth<br/>API key / OAuth JWT"]
    CLIAuth["CLI auth<br/>configured principal"]
    Authorizer["core.domain.auth<br/>Authorizer + PermissionAuthPolicy"]
    AuthorizedInterface["AuthorizedEvernightInterface"]
    Interface["EvernightInterface"]

    ToolCall["ToolCall"]
    ToolPolicy["BasicToolSafetyPolicy"]
    Approval["ToolApprovalDecision<br/>or metadata.approved"]
    ToolExecutor["Tool executor"]

    SensitiveTargets["Sensitive targets<br/>write / process / network / database"]
    BlockedTargets["Blocked permissions<br/>shell / destructive by default"]

    User --> HTTPAuth
    User --> CLIAuth
    HTTPAuth --> Authorizer
    CLIAuth --> Authorizer
    Authorizer --> AuthorizedInterface
    AuthorizedInterface --> Interface

    Interface --> ToolCall
    ToolCall --> ToolPolicy
    ToolPolicy --> Approval
    Approval --> ToolExecutor
    ToolExecutor --> SensitiveTargets

    ToolPolicy -. rejects .-> BlockedTargets
```

## 6. Deployment Relationship

```mermaid
flowchart TD
    Operator["Developer / Operator"]
    ConfigFile["config.toml"]
    Env["Environment variables<br/>provider keys / auth / runtime paths"]

    CLIProcess["evernight<br/>CLI process"]
    HTTPProcess["evernight-http / uvicorn<br/>HTTP process"]
    StaticFrontend["frontend/dist<br/>optional static UI"]

    AppFactory["EvernightAI.bootstrap.http:create_app"]
    Runtime["RuntimeKernel"]
    SQLite[".evernight/runtime.sqlite3<br/>or configured SQLite path"]

    Providers["External LLM APIs<br/>OpenAI-compatible / Responses / Gemini / Anthropic"]
    Web["Web targets"]
    Filesystem["Configured filesystem root"]
    Shell["Allowlisted shell commands"]
    Git["Configured git repository"]
    Project["Allowlisted project tasks"]

    Operator --> ConfigFile
    Operator --> Env

    ConfigFile --> CLIProcess
    Env --> CLIProcess
    ConfigFile --> HTTPProcess
    Env --> HTTPProcess

    HTTPProcess --> AppFactory
    AppFactory --> Runtime
    CLIProcess --> Runtime

    HTTPProcess --> StaticFrontend
    Runtime --> SQLite
    Runtime --> Providers
    Runtime --> Web
    Runtime --> Filesystem
    Runtime --> Shell
    Runtime --> Git
    Runtime --> Project
```
