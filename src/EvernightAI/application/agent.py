"""Public agent services with separate execution, persistence and recovery modules."""

from EvernightAI.application.agent_execution import AgentExecutionApplication
from EvernightAI.application.agent_lifecycle import (
    _AgentRunLifecycle,
)
from EvernightAI.application.agent_recovery import (
    AgentRunRecoveryCheckpoint,
    inspect_agent_run_checkpoint,
    latest_active_agent_run_lease,
    recover_interrupted_agent_runs,
)
from EvernightAI.application.agent_runs import (
    AgentRunApplication,
)
from EvernightAI.application.agent_state import (
    AbandonedToolExecution,
    AgentResumeMode,
    AgentRunMetadata,
    AgentRunRetryPlan,
    agent_resume_mode,
    agent_run_can_resume,
    agent_run_failure,
)
from EvernightAI.core.protocol.interface import AgentInterfaceProtocol
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunState
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.tool import ToolApprovalDecision

__all__ = [
    "AbandonedToolExecution",
    "AgentApplication",
    "AgentResumeMode",
    "AgentRunApplication",
    "AgentRunMetadata",
    "AgentRunRecoveryCheckpoint",
    "AgentRunRetryPlan",
    "_AgentRunLifecycle",
    "agent_resume_mode",
    "agent_run_can_resume",
    "agent_run_failure",
    "inspect_agent_run_checkpoint",
    "latest_active_agent_run_lease",
    "recover_interrupted_agent_runs",
]


class AgentApplication(AgentExecutionApplication, AgentInterfaceProtocol):
    async def start_agent_run(
        self,
        request: AgentRunRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        return await AgentRunApplication(self._runtime, agent=self).start(
            request,
            principal_scope=principal_scope,
        )

    async def resume_agent_run(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        return await AgentRunApplication(self._runtime, agent=self).resume(
            run_id,
            approvals,
            principal_scope=principal_scope,
        )
