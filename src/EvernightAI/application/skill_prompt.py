from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.error.skill import SkillInputError
from EvernightAI.core.schema.content import ChatRequest, ChatSkill, Content
from EvernightAI.core.schema.tool import ToolDefinition
from EvernightAI.core.error.skill import SkillDisabledError
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillRenderRequest,
)


async def render_chat_skill_messages(
    runtime: RuntimeProtocol,
    skills: list[ChatSkill] | None,
    capability: SkillCapability,
    tools: list[ToolDefinition] | None = None,
) -> tuple[list[Content], list[RenderedSkill]]:
    rendered_skills: list[RenderedSkill] = []
    messages: list[Content] = []

    for index, skill in enumerate(skills or []):
        definition = runtime.skills.get_skill(skill.skill_name)
        if not definition.is_enabled:
            raise SkillDisabledError(f"The skill {skill.skill_name} is disabled")
        available_tools = {tool.name for tool in tools or []}
        missing = [name for name in definition.required_tools if name not in available_tools]
        if missing:
            raise SkillInputError(f"The skill {skill.skill_name} requires tools: {', '.join(missing)}")
        if not runtime.skills.supports(skill.skill_name, capability):
            raise SkillInputError(
                f"The skill {skill.skill_name} does not support {capability.value}"
            )

        rendered = await runtime.skills.render(
            SkillRenderRequest(
                render_id=skill.render_id or f"{skill.skill_name}-{index}",
                skill_name=skill.skill_name,
                variables=skill.variables,
                metadata=skill.metadata,
            )
        )
        rendered_skills.append(rendered)
        messages.extend(rendered.messages)

    return messages, rendered_skills


async def compose_skill_prompted_chat_request(
    runtime: RuntimeProtocol,
    request: ChatRequest,
    capability: SkillCapability,
) -> ChatRequest:
    skill_messages, rendered_skills = await render_chat_skill_messages(
        runtime,
        request.skills,
        capability,
        request.tools,
    )
    if not rendered_skills:
        return request

    metadata = dict(request.metadata)
    metadata["skill_names"] = [skill.skill_name for skill in request.skills or []]
    metadata["skill_render_ids"] = [skill.render_id for skill in rendered_skills]

    return request.model_copy(
        update={
            "messages": [*skill_messages, *request.messages],
            "skills": None,
            "metadata": metadata,
        }
    )
