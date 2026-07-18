from EvernightAI.application.memory import select_memories_for_request
from EvernightAI.application.skill_prompt import compose_skill_prompted_chat_request
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.content import ChatRequest, ChatSkill, Content
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.skill import SkillCapability
from EvernightAI.core.schema.tool import ToolDefinition


class ChatRequestComposer:
    """Compose the model-visible request shared by Chat and Agent flows."""

    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def compose(
        self,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        principal_scope: PrincipalScope | None = None,
        skill_capability: SkillCapability | None = None,
    ) -> ChatRequest:
        context = await self._runtime.contexts.get(
            context_id,
            principal_scope=principal_scope,
        )
        memory_selection = await select_memories_for_request(
            self._runtime,
            explicit_query=memory_query,
            context_id=context.context_id,
            metadata=metadata,
            owner_id=context.owner_id,
            principal_scope=principal_scope,
        )
        request = self._runtime.context_strategy.compose_chat_request(
            context,
            model_id=model_id,
            messages=messages,
            memory_selection=memory_selection,
            tools=tools,
            metadata=metadata,
        ).model_copy(update={"skills": skills})
        if skill_capability is None:
            return request
        return await compose_skill_prompted_chat_request(
            self._runtime,
            request,
            skill_capability,
        )
