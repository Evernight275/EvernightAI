from typing import Annotated

from fastapi import APIRouter, Body

from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillRenderRequest,
    SkillCapability,
    SkillDefinition,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.schema import RenderSkillRequest
from EvernightAI.interface.http.template import (
    RENDER_SKILL_EXAMPLES,
)


router = APIRouter(prefix="/skills", tags=["skills"])


@router.get(
    "",
    response_model=list[SkillDefinition],
    response_model_exclude_none=True,
    summary="List skills",
    operation_id="list_skills",
)
async def list_skills(interface: InterfaceDependency) -> list[SkillDefinition]:
    return interface.skills.list_skills()


@router.get(
    "/{skill_name}",
    response_model=SkillDefinition,
    response_model_exclude_none=True,
    summary="Get a skill",
    operation_id="get_skill",
)
async def get_skill(
    skill_name: str,
    interface: InterfaceDependency,
) -> SkillDefinition:
    return interface.skills.get_skill(skill_name)


@router.get(
    "/{skill_name}/supports",
    response_model=bool,
    response_model_exclude_none=True,
    summary="Check skill capability",
    operation_id="skill_supports",
)
async def skill_supports(
    skill_name: str,
    capability: SkillCapability,
    interface: InterfaceDependency,
) -> bool:
    return interface.skills.skill_supports(skill_name, capability)


@router.post(
    "/{skill_name}/render",
    response_model=RenderedSkill,
    response_model_exclude_none=True,
    summary="Render a skill prompt",
    description=(
        "Render a registered skill into prompt messages. Chat requests can also "
        "declare skills directly by name."
    ),
    operation_id="render_skill",
)
async def render_skill(
    skill_name: str,
    request: Annotated[
        RenderSkillRequest,
        Body(openapi_examples=RENDER_SKILL_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> RenderedSkill:
    return await interface.skills.render_skill(
        SkillRenderRequest(
            render_id=request.render_id or f"{skill_name}-0",
            skill_name=skill_name,
            variables=request.variables,
            metadata=request.metadata,
        )
    )
