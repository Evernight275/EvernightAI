from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunResult,
    AgentStep,
    AgentStepType,
)
from EvernightAI.core.schema.content import (
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.memory import MemoryQuery
from EvernightAI.core.schema.tool import ToolCall, ToolCallResult, ToolDefinition


class AgentApplication:
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def run_agent(self, request: AgentRunRequest) -> AgentRunResult:
        steps: list[AgentStep] = []

        response = await self._chat(
            request.provider_id,
            request.context_id,
            model_id=request.model_id,
            messages=request.messages,
            memory_query=request.memory_query,
            tools=request.tools,
            metadata=request.metadata,
        )
        steps.append(
            AgentStep(
                step_type=AgentStepType.CHAT,
                response=response,
                message=response.message,
            )
        )
        for message in request.messages:
            await self._runtime.contexts.append(request.context_id, message)
        await self._runtime.contexts.append(request.context_id, response.message)

        remaining_rounds = request.max_tool_rounds
        while response.message.tool_calls and remaining_rounds > 0:
            for call in response.message.tool_calls:
                tool_result = await self._runtime.tools.execute(call)
                tool_message = self._tool_result_to_message(tool_result)
                steps.append(
                    AgentStep(
                        step_type=AgentStepType.TOOL,
                        message=tool_message,
                        tool_call=call,
                        tool_result=tool_result,
                    )
                )
                await self._runtime.contexts.append(request.context_id, tool_message)

            response = await self._chat(
                request.provider_id,
                request.context_id,
                model_id=request.model_id,
                messages=[],
                tools=request.tools,
                metadata=request.metadata,
            )
            steps.append(
                AgentStep(
                    step_type=AgentStepType.CHAT,
                    response=response,
                    message=response.message,
                )
            )
            await self._runtime.contexts.append(request.context_id, response.message)
            remaining_rounds -= 1

        return AgentRunResult(
            response=response,
            steps=steps,
            metadata={
                **request.metadata,
                "tool_rounds_used": request.max_tool_rounds - remaining_rounds,
            },
        )

    async def run(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        max_tool_rounds: int = 1,
    ) -> ChatResponse:
        result = await self.run_agent(
            AgentRunRequest(
                provider_id=provider_id,
                context_id=context_id,
                model_id=model_id,
                messages=messages,
                memory_query=memory_query,
                tools=tools,
                max_tool_rounds=max_tool_rounds,
                metadata=dict(metadata or {}),
            )
        )
        return result.response

    async def _chat(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatResponse:
        context = await self._runtime.contexts.get(context_id)
        memory_selection = (
            self._runtime.memory_strategy.select(
                await self._runtime.memories.list_memories(),
                memory_query,
            )
            if memory_query is not None
            else None
        )
        request = self._runtime.context_strategy.compose_chat_request(
            context,
            model_id=model_id,
            messages=messages,
            memory_selection=memory_selection,
            tools=tools,
            metadata=metadata,
        )
        return await self._runtime.providers.chat(provider_id, request)

    def _tool_result_to_message(self, result: ToolCallResult) -> Content:
        return Content(
            role=MessageRole.TOOL,
            tool_call_id=result.tool_call_id,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=result.model_dump_json(),
                )
            ],
        )
