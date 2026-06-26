from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.content import MessageStatus
from EvernightAI.core.schema.context import Context


async def mark_retry_messages(
    runtime: RuntimeProtocol,
    context_id: str,
    retry_from_message_index: int | None,
) -> None:
    if retry_from_message_index is None:
        return

    context = await runtime.contexts.get(context_id)
    if retry_from_message_index >= len(context.messages):
        raise ChatInputError("Retry message index is out of range")

    await runtime.contexts.replace(
        _mark_context_retry_messages(context, retry_from_message_index)
    )


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
