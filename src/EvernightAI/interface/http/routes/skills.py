from fastapi import APIRouter

from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillRenderRequest,
    SkillCapability,
    SkillDefinition,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.schema import RenderSkillRequest


router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillDefinition])
async def list_skills(interface: InterfaceDependency) -> list[SkillDefinition]:
    return interface.skills.list_skills()


@router.get("/{skill_name}", response_model=SkillDefinition)
async def get_skill(
    skill_name: str,
    interface: InterfaceDependency,
) -> SkillDefinition:
    return interface.skills.get_skill(skill_name)


@router.get("/{skill_name}/supports", response_model=bool)
async def skill_supports(
    skill_name: str,
    capability: SkillCapability,
    interface: InterfaceDependency,
) -> bool:
    return interface.skills.skill_supports(skill_name, capability)


@router.post("/{skill_name}/render", response_model=RenderedSkill)
async def render_skill(
    skill_name: str,
    request: RenderSkillRequest,
    interface: InterfaceDependency,
) -> RenderedSkill:
    return await interface.skills.render_skill(
        SkillRenderRequest(
            render_id=request.render_id,
            skill_name=skill_name,
            variables=request.variables,
            metadata=request.metadata,
        )
    )
