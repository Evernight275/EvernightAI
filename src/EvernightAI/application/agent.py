import json

from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunResult,
    AgentStep,
    AgentStepType,
    AgentStopReason,
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
        steps: list[AgentStep] = [
            AgentStep(
                step_type=AgentStepType.START,
                metadata={
                    "provider_id": request.provider_id,
                    "context_id": request.context_id,
                    "model_id": request.model_id,
                },
            )
        ]

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
        stop_reason = AgentStopReason.FINISHED
        while response.message.tool_calls and remaining_rounds > 0:
            for call in response.message.tool_calls:
                try:
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
                except Exception as exc:
                    tool_message = self._tool_error_to_message(call, exc)
                    steps.append(
                        AgentStep(
                            step_type=AgentStepType.TOOL_ERROR,
                            message=tool_message,
                            tool_call=call,
                            error_type=exc.__class__.__name__,
                            error_message=str(exc),
                        )
                    )
                    if not request.recover_tool_errors:
                        await self._runtime.contexts.append(
                            request.context_id,
                            tool_message,
                        )
                        stop_reason = AgentStopReason.TOOL_ERROR
                        result = AgentRunResult(
                            response=response,
                            stop_reason=stop_reason,
                            steps=[
                                *steps,
                                AgentStep(
                                    step_type=AgentStepType.STOP,
                                    metadata={"reason": stop_reason.value},
                                ),
                            ],
                            metadata={
                                **request.metadata,
                                "tool_rounds_used": (
                                    request.max_tool_rounds - remaining_rounds
                                ),
                            },
                        )
                        await self._write_memories(request, result, steps)
                        return result

                await self._runtime.contexts.append(request.context_id, tool_message)

            remaining_rounds -= 1
            if remaining_rounds < 0:
                break

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

        if response.message.tool_calls:
            stop_reason = AgentStopReason.TOOL_ROUNDS_EXHAUSTED

        steps.append(
            AgentStep(
                step_type=AgentStepType.STOP,
                metadata={"reason": stop_reason.value},
            )
        )
        result = AgentRunResult(
            response=response,
            stop_reason=stop_reason,
            steps=steps,
            metadata={
                **request.metadata,
                "tool_rounds_used": request.max_tool_rounds - remaining_rounds,
            },
        )
        await self._write_memories(request, result, steps)
        return result

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
                recover_tool_errors=True,
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

    def _tool_error_to_message(self, call: ToolCall, exc: Exception) -> Content:
        payload = {
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }
        return Content(
            role=MessageRole.TOOL,
            tool_call_id=call.tool_call_id,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=json.dumps(payload, ensure_ascii=False),
                )
            ],
            metadata={
                "error": True,
                "error_type": exc.__class__.__name__,
            },
        )

    async def _write_memories(
        self,
        request: AgentRunRequest,
        result: AgentRunResult,
        steps: list[AgentStep],
    ) -> None:
        memories = self._runtime.memory_write_strategy.create_memories(
            request,
            result,
        )
        for memory in memories:
            await self._runtime.memories.create(memory)
            memory_step = AgentStep(
                step_type=AgentStepType.MEMORY_WRITE,
                metadata={"memory_id": memory.memory_id},
            )
            steps.append(memory_step)
            result.steps.append(
                AgentStep(
                    step_type=memory_step.step_type,
                    metadata=dict(memory_step.metadata),
                )
            )
