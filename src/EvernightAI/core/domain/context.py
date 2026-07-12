from EvernightAI.core.error.context import ContextNotFoundError
from EvernightAI.core.protocol.context import (
    ContextOrganizerProtocol,
    ContextStrategyProtocol,
    ContextSummarizerProtocol,
    ContextTokenEstimatorProtocol,
    ContextManageProtocol,
    ContextRegisterProtocol,
)
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageStatus,
    MessageRole,
)
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.context import Context, ContextWindow
from EvernightAI.core.schema.memory import MemorySelection
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition


def _scope_permits(
    principal_scope: PrincipalScope | None,
    owner_id: str | None,
) -> bool:
    return principal_scope is None or principal_scope.permits(owner_id)


def _require_context_scope(
    context: Context,
    principal_scope: PrincipalScope | None,
) -> None:
    if not _scope_permits(principal_scope, context.owner_id):
        raise ContextNotFoundError(
            f"The context {context.context_id} is not available in this scope"
        )


class ContextRegister(ContextRegisterProtocol):
    def __init__(self) -> None:
        self._contexts: dict[str, Context] = {}

    def register(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注册上下文"""
        _require_context_scope(context, principal_scope)
        self._contexts[context.context_id] = context

    def unregister(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注销上下文"""
        if not self.has(context_id, principal_scope=principal_scope):
            raise ContextNotFoundError(f"The context {context_id} is not registered")

        self._contexts.pop(context_id, None)

    def get(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        """获取上下文"""
        if self.has(context_id, principal_scope=principal_scope):
            return self._contexts[context_id]

        raise ContextNotFoundError(f"The context {context_id} is not found")

    def has(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> bool:
        """检查上下文是否存在"""
        context = self._contexts.get(context_id)
        return context is not None and _scope_permits(principal_scope, context.owner_id)

    def list_contexts(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Context]:
        """列出所有上下文"""
        contexts = sorted(self._contexts.values(), key=lambda item: item.context_id)
        if cursor is not None:
            contexts = [item for item in contexts if item.context_id > cursor]
        if principal_scope is not None and principal_scope.owner_id is not None:
            if owner_id is not None and owner_id != principal_scope.owner_id:
                return []
            owner_id = principal_scope.owner_id
        if owner_id is not None:
            contexts = [item for item in contexts if item.owner_id == owner_id]
        return contexts if limit is None else contexts[:limit]


class ContextManager(ContextManageProtocol):
    def __init__(self, register: ContextRegisterProtocol) -> None:
        self._register = register

    async def create(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        """创建上下文"""
        self._register.register(context, principal_scope=principal_scope)
        return self._register.get(
            context.context_id,
            principal_scope=principal_scope,
        )

    async def get(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        """获取上下文"""
        return self._register.get(context_id, principal_scope=principal_scope)

    async def append(
        self,
        context_id: str,
        message: Content,
        *,
        expected_revision: int | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        """追加上下文消息"""
        return self._register.append_message(
            context_id,
            message,
            expected_revision=expected_revision,
            principal_scope=principal_scope,
        )

    async def replace(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        """替换上下文"""
        if not self._register.has(
            context.context_id,
            principal_scope=principal_scope,
        ):
            raise ContextNotFoundError(f"The context {context.context_id} is not found")

        self._register.register(context, principal_scope=principal_scope)
        return self._register.get(
            context.context_id,
            principal_scope=principal_scope,
        )

    async def list_contexts(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Context]:
        """列出所有上下文"""
        return self._register.list_contexts(
            cursor=cursor,
            limit=limit,
            owner_id=owner_id,
            principal_scope=principal_scope,
        )

    async def delete(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """删除上下文"""
        self._register.unregister(context_id, principal_scope=principal_scope)

    async def clear(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """清空上下文"""
        for context in list(
            self._register.list_contexts(principal_scope=principal_scope)
        ):
            self._register.unregister(
                context.context_id,
                principal_scope=principal_scope,
            )


class ContextOrganizer(ContextOrganizerProtocol):
    def organize(
        self,
        context: Context,
        *,
        messages: list[Content] | None = None,
    ) -> ContextWindow:
        """组织基础上下文窗口"""
        next_messages = messages or []
        return ContextWindow(
            context_id=context.context_id,
            messages=[
                *self._active_messages(context.messages),
                *self._active_messages(next_messages),
            ],
            metadata=dict(context.metadata),
        )

    def to_chat_request(
        self,
        context: Context,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest:
        """将基础上下文组织为聊天请求"""
        window = self.organize(context, messages=messages)
        return ChatRequest(
            model_id=model_id,
            messages=window.messages,
            tools=tools,
            metadata={
                **window.metadata,
                **(metadata or {}),
                "context_id": window.context_id,
            },
        )

    def _active_messages(self, messages: list[Content]) -> list[Content]:
        active_messages = [
            message
            for message in messages
            if message.status in {None, MessageStatus.ACTIVE}
        ]
        return self._tool_protocol_safe_messages(active_messages)

    def _tool_protocol_safe_messages(self, messages: list[Content]) -> list[Content]:
        safe_messages: list[Content] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role is MessageRole.TOOL:
                index += 1
                continue

            tool_calls = message.tool_calls or []
            if message.role is MessageRole.ASSISTANT and tool_calls:
                tool_messages = self._following_tool_messages(messages, index, tool_calls)
                if len(tool_messages) == len(tool_calls):
                    safe_messages.append(message)
                    safe_messages.extend(tool_messages)
                    index += 1 + len(tool_messages)
                    continue

                index += 1 + len(tool_messages)
                continue

            safe_messages.append(message)
            index += 1

        return safe_messages

    def _following_tool_messages(
        self,
        messages: list[Content],
        assistant_index: int,
        tool_calls: list[ToolCall],
    ) -> list[Content]:
        expected_ids = {call.tool_call_id for call in tool_calls}
        seen_ids: set[str] = set()
        tool_messages: list[Content] = []
        for message in messages[assistant_index + 1 :]:
            if message.role is not MessageRole.TOOL:
                break
            if message.tool_call_id not in expected_ids:
                break
            if message.tool_call_id in seen_ids:
                break

            seen_ids.add(message.tool_call_id)
            tool_messages.append(message)
            if seen_ids == expected_ids:
                break

        return tool_messages


class BasicContextStrategy(ContextStrategyProtocol):
    def __init__(self, organizer: ContextOrganizerProtocol) -> None:
        self._organizer = organizer

    def compose_chat_request(
        self,
        context: Context,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        memory_selection: MemorySelection | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest:
        """组合基础聊天请求"""
        next_messages = list(messages or [])
        request_metadata: dict[str, object] = dict(metadata or {})
        memory_message: Content | None = None

        if memory_selection is not None:
            memory_message = self._compose_memory_message(memory_selection)
            request_metadata["memory_ids"] = [
                memory.memory_id for memory in memory_selection.memories
            ]
            request_metadata["memory_selection"] = dict(memory_selection.metadata)

        request = self._organizer.to_chat_request(
            context,
            model_id=model_id,
            messages=next_messages,
            tools=tools,
            metadata=request_metadata,
        )
        if memory_message is None:
            return request

        return request.model_copy(
            update={
                "messages": _insert_after_system_prefix(
                    request.messages,
                    memory_message,
                )
            }
        )

    def _compose_memory_message(self, selection: MemorySelection) -> Content | None:
        if not selection.memories:
            return None

        lines = ["Relevant memory:"]
        for memory in selection.memories:
            lines.append(f"- {memory.kind.value}: {memory.content}")

        return Content(
            role=MessageRole.SYSTEM,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text="\n".join(lines),
                )
            ],
            metadata={
                "source": "memory",
                "memory_ids": [memory.memory_id for memory in selection.memories],
            },
        )


class ApproximateContextTokenEstimator(ContextTokenEstimatorProtocol):
    def estimate(self, message: Content) -> int:
        serialized = message.model_dump_json(exclude_none=True)
        return max(1, (len(serialized) + 3) // 4)


class WindowTrimmingContextStrategy(ContextStrategyProtocol):
    def __init__(
        self,
        strategy: ContextStrategyProtocol,
        *,
        max_messages: int,
    ) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        self._strategy = strategy
        self._max_messages = max_messages

    def compose_chat_request(
        self,
        context: Context,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        memory_selection: MemorySelection | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest:
        request = self._strategy.compose_chat_request(
            context,
            model_id=model_id,
            messages=messages,
            memory_selection=memory_selection,
            tools=tools,
            metadata=metadata,
        )
        trimmed, trim_metadata = _preserve_system_prefix(
            request.messages,
            max_items=self._max_messages,
            protected_ids=_protected_message_ids(messages),
        )
        return _with_context_strategy_metadata(
            request,
            messages=trimmed,
            strategy=self.__class__.__name__,
            original_message_count=len(request.messages),
            retained_message_count=len(trimmed),
            max_messages=self._max_messages,
            **trim_metadata,
        )


class TokenBudgetContextStrategy(ContextStrategyProtocol):
    def __init__(
        self,
        strategy: ContextStrategyProtocol,
        *,
        max_tokens: int,
        estimator: ContextTokenEstimatorProtocol | None = None,
    ) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        self._strategy = strategy
        self._max_tokens = max_tokens
        self._estimator = estimator or ApproximateContextTokenEstimator()

    def compose_chat_request(
        self,
        context: Context,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        memory_selection: MemorySelection | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest:
        request = self._strategy.compose_chat_request(
            context,
            model_id=model_id,
            messages=messages,
            memory_selection=memory_selection,
            tools=tools,
            metadata=metadata,
        )
        selected, budget_metadata = self._within_budget(
            request.messages,
            protected_ids=_protected_message_ids(messages),
        )
        return _with_context_strategy_metadata(
            request,
            messages=selected,
            strategy=self.__class__.__name__,
            token_budget=self._max_tokens,
            estimated_tokens=sum(self._estimator.estimate(item) for item in selected),
            **budget_metadata,
        )

    def _within_budget(
        self,
        messages: list[Content],
        *,
        protected_ids: set[int] | None = None,
    ) -> tuple[list[Content], dict[str, object]]:
        prefix, remainder = _system_prefix(messages)
        protected_ids = protected_ids or set()
        selected_prefix = list(prefix)
        used = sum(self._estimator.estimate(message) for message in selected_prefix)
        reasons: list[str] = []
        if used > self._max_tokens:
            reasons.append("system_prefix_exceeds_token_budget")

        groups = _message_groups(remainder)
        for message in prefix:
            protected_ids.add(id(message))

        selected_indexes: set[int] = set()
        for index, group in enumerate(groups):
            if not _group_contains_protected_message(group, protected_ids):
                continue
            cost = sum(self._estimator.estimate(message) for message in group)
            selected_indexes.add(index)
            used += cost

        if used > self._max_tokens and selected_indexes:
            reasons.append("protected_messages_exceed_token_budget")

        elastic_used = 0
        for index in reversed(range(len(groups))):
            if index in selected_indexes:
                continue
            group = groups[index]
            cost = sum(self._estimator.estimate(message) for message in group)
            if used + elastic_used + cost > self._max_tokens:
                if not selected_indexes and elastic_used == 0 and index == len(groups) - 1:
                    selected_indexes.add(index)
                    elastic_used += cost
                    reasons.append("newest_message_group_exceeds_token_budget")
                continue
            selected_indexes.add(index)
            elastic_used += cost

        selected_tail = [
            message
            for index, group in enumerate(groups)
            if index in selected_indexes
            for message in group
        ]
        selected = [*selected_prefix, *selected_tail]
        dropped_count = len(messages) - len(selected)
        if dropped_count:
            reasons.append("token_budget_dropped_messages")

        return selected, _degradation_metadata(
            reasons,
            dropped_message_count=dropped_count,
        )


class SummarizingContextStrategy(ContextStrategyProtocol):
    def __init__(
        self,
        strategy: ContextStrategyProtocol,
        summarizer: ContextSummarizerProtocol,
        *,
        summarize_after_messages: int,
        keep_recent_messages: int,
    ) -> None:
        if summarize_after_messages < 1:
            raise ValueError("summarize_after_messages must be at least 1")
        if keep_recent_messages < 1:
            raise ValueError("keep_recent_messages must be at least 1")
        self._strategy = strategy
        self._summarizer = summarizer
        self._summarize_after_messages = summarize_after_messages
        self._keep_recent_messages = keep_recent_messages

    def compose_chat_request(
        self,
        context: Context,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        memory_selection: MemorySelection | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest:
        request = self._strategy.compose_chat_request(
            context,
            model_id=model_id,
            messages=messages,
            memory_selection=memory_selection,
            tools=tools,
            metadata=metadata,
        )
        if len(request.messages) <= self._summarize_after_messages:
            return request
        prefix, remainder = _system_prefix(request.messages)
        if len(remainder) <= self._keep_recent_messages:
            return request
        groups = _message_groups(remainder)
        recent_groups = _tail_groups_by_message_count(
            groups,
            self._keep_recent_messages,
        )
        recent_group_count = len(recent_groups)
        removed_groups = (
            groups[:-recent_group_count] if recent_group_count else groups
        )
        removed = [message for group in removed_groups for message in group]
        recent = [message for group in recent_groups for message in group]
        if not removed:
            return request
        summary = self._summarizer.summarize(removed)
        return _with_context_strategy_metadata(
            request,
            messages=[*prefix, summary, *recent],
            strategy=self.__class__.__name__,
            summarized_message_count=len(removed),
        )


def _system_prefix(messages: list[Content]) -> tuple[list[Content], list[Content]]:
    index = 0
    while index < len(messages) and messages[index].role is MessageRole.SYSTEM:
        index += 1
    return messages[:index], messages[index:]


def _insert_after_system_prefix(
    messages: list[Content],
    message: Content,
) -> list[Content]:
    prefix, remainder = _system_prefix(messages)
    return [*prefix, message, *remainder]


def _protected_message_ids(messages: list[Content] | None) -> set[int]:
    if messages is None:
        return set()
    return {
        id(message)
        for message in messages
        if message.status in {None, MessageStatus.ACTIVE}
    }


def _preserve_system_prefix(
    messages: list[Content],
    *,
    max_items: int,
    protected_ids: set[int] | None = None,
) -> tuple[list[Content], dict[str, object]]:
    prefix, remainder = _system_prefix(messages)
    protected_ids = protected_ids or set()
    groups = _message_groups(remainder)
    selected_indexes: set[int] = set()
    reasons: list[str] = []
    protected_count = len(prefix)
    if len(prefix) > max_items:
        reasons.append("system_prefix_exceeds_max_messages")

    for index, group in enumerate(groups):
        if not _group_contains_protected_message(group, protected_ids):
            continue
        selected_indexes.add(index)
        protected_count += len(group)

    if protected_count > max_items and selected_indexes:
        reasons.append("protected_messages_exceed_max_messages")

    remaining = max_items - protected_count
    selected_count = 0
    for index in reversed(range(len(groups))):
        if index in selected_indexes:
            continue
        group = groups[index]
        if remaining >= 0 and selected_count + len(group) <= remaining:
            selected_indexes.add(index)
            selected_count += len(group)
            continue
        if not selected_indexes and selected_count == 0 and index == len(groups) - 1:
            selected_indexes.add(index)
            selected_count += len(group)
            reasons.append("newest_message_group_exceeds_max_messages")

    selected_tail = [
        message
        for index, group in enumerate(groups)
        if index in selected_indexes
        for message in group
    ]
    selected = [*prefix, *selected_tail]
    dropped_count = len(messages) - len(selected)
    if dropped_count:
        reasons.append("max_messages_dropped_messages")

    return selected, _degradation_metadata(
        reasons,
        dropped_message_count=dropped_count,
    )


def _message_groups(messages: list[Content]) -> list[list[Content]]:
    groups: list[list[Content]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        group = [message]
        if message.role is MessageRole.ASSISTANT and message.tool_calls:
            expected_ids = {call.tool_call_id for call in message.tool_calls}
            next_index = index + 1
            while next_index < len(messages):
                candidate = messages[next_index]
                if (
                    candidate.role is not MessageRole.TOOL
                    or candidate.tool_call_id not in expected_ids
                ):
                    break
                group.append(candidate)
                next_index += 1
            index = next_index
        else:
            index += 1
        groups.append(group)
    return groups


def _group_contains_protected_message(
    group: list[Content],
    protected_ids: set[int],
) -> bool:
    return any(id(message) in protected_ids for message in group)


def _tail_groups_by_message_count(
    groups: list[list[Content]],
    max_items: int,
) -> list[list[Content]]:
    selected: list[list[Content]] = []
    count = 0
    for group in reversed(groups):
        if selected and count + len(group) > max_items:
            break
        selected.append(group)
        count += len(group)
        if count >= max_items:
            break
    selected.reverse()
    return selected


def _with_context_strategy_metadata(
    request: ChatRequest,
    *,
    messages: list[Content],
    strategy: str,
    **values: object,
) -> ChatRequest:
    strategy_metadata = {"name": strategy, **values}
    steps = request.metadata.get("context_strategy_steps")
    step_list = list(steps) if isinstance(steps, list) else []
    step_list.append(strategy_metadata)
    return request.model_copy(
        update={
            "messages": messages,
            "metadata": {
                **request.metadata,
                "context_strategy": strategy_metadata,
                "context_strategy_steps": step_list,
            },
        }
    )


def _degradation_metadata(
    reasons: list[str],
    *,
    dropped_message_count: int,
) -> dict[str, object]:
    if not reasons:
        return {
            "degraded": False,
            "degradation_reasons": [],
            "dropped_message_count": dropped_message_count,
        }
    return {
        "degraded": True,
        "degradation_reasons": list(dict.fromkeys(reasons)),
        "dropped_message_count": dropped_message_count,
    }
