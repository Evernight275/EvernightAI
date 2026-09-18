# 前端接口入口

设置弹窗及独立设置页共享这些入口，所有请求经过现有 API client 的认证和错误处理。

| 后端能力 | 页面入口 |
| --- | --- |
| Provider 新建、列表、模型列表、删除 | 连接与认证 → 模型服务管理 |
| 单个模型详情、服务能力检查 | 工作区资源 → 模型 |
| Memory 创建、查询、编辑、启用、停用、删除、选择 | 记忆管理；复杂选择条件位于工作区资源 → 记忆 |
| Session 创建、加载、删除 | 聊天侧栏 |
| Session 标题更新 | 聊天标题旁编辑按钮 |
| Session 查询、归档、恢复 | 工作区资源 → 会话 |
| Context 创建、列表、消息查询、追加、替换、删除 | 工作区资源 → 上下文 |
| Context compose-preview | 输入框上方「技能与上下文」；工作区资源 → 上下文 |
| Skills 列表、详情、能力检查、render | 聊天技能选择；工作区资源 → 工具与技能 |
| Tools 列表、权限信息 | 工作区资源 → 工具与技能；聊天审批面板 |
| Data source、fields、metrics、statistics、analyze | 数据分析；复杂过滤、排序参数位于工作区资源 → 数据分析 |
| Logs 查询、游标查询、清除 | 工作区资源 → 日志 |
| Health、ready | 常规状态；工作区资源 → 服务状态 |
| Agent 列表、详情、pause、cancel、retry、resume | 运行管理；聊天停止、恢复、重试入口 |
| Agent trace、tool-executions | 运行管理及工作区资源 → 运行记录 |
| Tool execution resolve | 工作区资源 → 运行记录 → 处理未确定的工具执行 |
| WebSocket trace 订阅/取消订阅 | 运行管理 → 实时轨迹 / 停止订阅 |
| Direct chat、context chat、session chat、session agent | 工作区资源 → 模型调试 |

聊天采用 Agent SSE 流式请求；普通请求、SSE 和 WebSocket 是相同能力的不同传输方式，不逐一制作重复页面。`approve-pending` 的全部批准便捷接口不直接暴露：运行管理要求对每个工具作出决定，再用 resume 提交。服务端没有 Provider 更新接口，因此只提供添加与删除，不模拟先删后建来更新。

高级资源工具中的 JSON 表单保留后端请求结构，解析失败不发送请求。删除、替换上下文、取消运行、清除日志和执行恢复有明确确认。操作只在用户触发时执行。实时订阅离开运行管理后关闭。

验证：`pnpm run check` 和 `pnpm run test:browser`。浏览器使用模拟接口覆盖失败重试、确认、逐项审批、记忆编辑、标题更新、技能预览与发送，不访问真实模型或删除真实数据。
