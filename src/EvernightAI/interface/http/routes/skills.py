from fastapi import APIRouter

from EvernightAI.core.schema.skill import (
    SkillCall,
    SkillCapability,
    SkillDefinition,
    SkillResult,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.schema import ExecuteSkillRequest


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


@router.post("/{skill_name}/execute", response_model=SkillResult)
async def execute_skill(
    skill_name: str,
    request: ExecuteSkillRequest,
    interface: InterfaceDependency,
) -> SkillResult:
    return await interface.skills.execute_skill(
        SkillCall(
            skill_call_id=request.skill_call_id,
            skill_name=skill_name,
            arguments=request.arguments,
            metadata=request.metadata,
        )
    )
