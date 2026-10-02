# 现场验证示例

用项目已有的装配入口、协议和 schema 构造最小场景：

```text
load_config -> ProviderConfig
create_runtime -> create_interface -> interface.providers.create_provider
ChatRequest -> interface.chat.chat / chat_stream -> ChatResponse / ChatStreamEvent
```

`provider_probe.py` 读取配置中的 Provider，用内存 Runtime 直接调用应用接口。
它不启动 HTTP 服务，不读取或更新业务 SQLite 中已保存的 Provider，也不加载
配置中的工具、MCP 或认证服务。凭证来自所选 TOML 及其引用的当前进程环境变量。

## 运行

在项目根目录执行，默认读取当前目录的 `config.toml`。
这些命令会实际调用供应商，可能产生少量用量。

```bash
# 只验证指定 Provider，便于隔离上游故障
uv run python examples/provider_probe.py --provider main

# 默认选择该 Provider 声明的第一个聊天模型；也可以手动指定模型
uv run python examples/provider_probe.py --provider main --model your-model-id

# 选择配置文件、每次调用的总时限，以及结果保存位置
uv run python examples/provider_probe.py --config config.toml --provider main --timeout 60 --report .evernight/provider-probe.json

# 验证配置中的全部 Provider
uv run python examples/provider_probe.py
```

Windows 也可以将 `uv run python` 替换成 `.\.venv\Scripts\python.exe`；
Linux 可以使用 `.venv/bin/python`。

## 验证范围

每个启用且选定了聊天模型的 Provider 执行四个场景：

| 场景 | 模型声明 | 调用方式 |
| --- | --- | --- |
| `declared_chat` | 已声明 | 普通聊天 |
| `declared_stream` | 已声明 | 流式聊天 |
| `undeclared_chat` | 清空本地声明，仍请求同一模型 | 普通聊天 |
| `undeclared_stream` | 清空本地声明，仍请求同一模型 | 流式聊天 |

同组的普通和流式调用并发执行，共用一个 Provider 实例；两组之间删除并重新
创建实例。远端模型发现被关闭，用于验证调用不依赖 `/models`。
`--model` 指定的模型如果不在配置中，会先加入该次内存实例的声明。

成功要求返回非空文本；流式还必须出现 `DONE`，且没有 `ERROR` 事件。
`request_unchanged` 检查调用前后的原始 `ChatRequest` 是否一致。
这里验证的是接口行为，不评价模型回答质量，也不等于完整的并发压力测试。

## 解释结果

脚本逐项输出 JSON，最后汇总通过、失败和跳过数量。报告不保存密钥、完整
上游错误消息或回复正文。只读错误类型与结构化上游状态，避免混淆服务登录和
供应商认证。

- `ProviderAuthorizationError`：供应商拒绝凭证；检查该 TOML 的 Provider 配置。
- `ProbeTimeout`：脚本的总时限到达，不能仅据此判断网络、上游或适配器谁有问题。
- `ProviderUnavailableError`：标记跳过，成功路径尚未验证。
- `EmptyOutput` / `IncompleteStream`：响应缺少文本或流没有完成。
- 禁用的 Provider、没有可选聊天模型的 Provider 会跳过；后者可以用 `--model` 指定。

退出码 `0` 表示所有选定场景通过；`1` 表示有失败或配置错误；`2` 表示没有失败，
但存在跳过或没有实际完成验证。跳过不算通过。

排障时先用 `--provider` 缩小范围。需要隔离外部依赖时，可在内存 Runtime 的
`provider_factory.register(...)` 中注入实现 `ProviderInstanceProtocol` 的替身，
继续使用同样的请求和接口；确认问题后将最小复现固化为回归测试。
