from EvernightAI.core.protocol.tool import ToolExecutorProtocol, ToolRegisterProtocol
from EvernightAI.core.schema.image_tool import ImageToolRequest
from EvernightAI.core.schema.tool import (
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
    ToolReplayPolicy,
)


def register_image_tool(
    register: ToolRegisterProtocol, executor: ToolExecutorProtocol
) -> None:
    register.register(
        ToolDefinition(
            name="generate_image",
            description="Generate images from a prompt or edit previously generated images. Omit references to generate; provide saved record_id/image_index references to edit. Uses a configured image model independently of the chat model. Results are saved and displayed to the user; return record references rather than Base64. Ask for image provider/model configuration if none is available.",
            parameters_schema=ImageToolRequest.model_json_schema(),
            permissions=[ToolPermission.EXTERNAL_API, ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            replay_policy=ToolReplayPolicy.IDEMPOTENT,
            idempotency_key_parameter="_idempotency_key",
            metadata={"supports_execution_context": True},
        ),
        executor,
    )
