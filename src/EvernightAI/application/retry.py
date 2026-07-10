from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.content import Content, MessageRole, MessageStatus
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.auth import PrincipalScope


async def mark_retry_messages(
    runtime: RuntimeProtocol,
    context_id: str,
    retry_from_message_index: int | None,
    *,
    principal_scope: PrincipalScope | None = None,
) -> None:
    if retry_from_message_index is None:
        return

    context = await runtime.contexts.get(
        context_id,
        principal_scope=principal_scope,
    )
    if retry_from_message_index >= len(context.messages):
        raise ChatInputError("Retry message index is out of range")
    _ensure_retry_target(context.messages[retry_from_message_index])

    await runtime.contexts.replace(
        _mark_context_retry_messages(context, retry_from_message_index),
        principal_scope=principal_scope,
    )


def _ensure_retry_target(message: Content) -> None:
    if message.role is not MessageRole.ASSISTANT:
        raise ChatInputError("Retry message index must point to an assistant message")
    if message.status not in {None, MessageStatus.ACTIVE}:
        raise ChatInputError("Retry message index must point to an active message")


def _mark_context_retry_messages(context: Context, retry_from_index: int) -> Context:
    messages = [
        (
            message
            if index < retry_from_index
            else message.model_copy(update={"status": MessageStatus.REJECTED})
        )
        for index, message in enumerate(context.messages)
    ]
    return context.model_copy(update={"messages": messages})
