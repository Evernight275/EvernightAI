import json
from string import Template

from EvernightAI.core.error.skill import SkillConfigurationError, SkillInputError
from EvernightAI.core.protocol.skill import SkillRendererProtocol
from EvernightAI.core.schema.content import Content, ContentPart, ContentPartType, MessageRole
from EvernightAI.core.schema.skill import RenderedSkill, SkillRenderRequest, SkillTemplateConfig


def create_template_renderer(config: SkillTemplateConfig) -> SkillRendererProtocol:
    template = Template(config.prompt)
    if not template.is_valid():
        raise SkillConfigurationError("Invalid template placeholder; use $name or ${name}, and $$ for a literal dollar")

    async def render(request: SkillRenderRequest) -> RenderedSkill:
        missing = [name for name in template.get_identifiers() if name not in request.variables]
        if missing:
            raise SkillInputError("Missing template variables", detail=json.dumps({"missing_fields": missing}))
        values = {
            name: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for name, value in request.variables.items()
        }
        return RenderedSkill(
            skill_name=request.skill_name, render_id=request.render_id,
            messages=[Content(role=MessageRole.SYSTEM, content=[
                ContentPart(type=ContentPartType.TEXT, text=template.substitute(values)),
            ])],
        )

    return render
