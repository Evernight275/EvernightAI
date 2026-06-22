from fastapi import APIRouter

from EvernightAI.core.schema.skill import SkillCall, SkillDefinition, SkillResult
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.schema import ExecuteSkillRequest


router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillDefinition])
async def list_skills(interface: InterfaceDependency) -> list[SkillDefinition]:
    return interface.skills.list_skills()


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
