import { computed, type ComputedRef } from 'vue'
import type { ToolApprovalRequest, ToolApprovalStatus } from '../../api'
import type { ApprovalStatuses } from '../../runtime/chatRuntime'

export type ChatRequestStatusProps = {
  state: string
  error: unknown
  workspaceNotice?: string | null
  pendingApprovals: ToolApprovalRequest[]
  approvalStatuses: ApprovalStatuses
}

export type ChatRequestStatusEmits = {
  retry: []
  approve: [approvalId: string]
  deny: [approvalId: string]
  resume: []
  details: []
}

export function useChatRequestStatus(
  props: ChatRequestStatusProps,
): {
  visible: ComputedRef<boolean>
  errorMessage: ComputedRef<string | null>
  approvalItems: ComputedRef<ChatApprovalItem[]>
  canRetry: ComputedRef<boolean>
  canResume: ComputedRef<boolean>
} {
  return {
    visible: computed(() => ['approvalRequired', 'resumeRequired', 'failed'].includes(props.state)
      || Boolean(props.error) || Boolean(props.workspaceNotice)),
    errorMessage: computed(() => formatChatError(props.error)),
    approvalItems: computed(() => props.state === 'approvalRequired'
      ? props.pendingApprovals.map((approval) => approvalItem(
        approval,
        props.approvalStatuses[approval.approval_id],
      ))
      : []),
    canRetry: computed(() => props.state === 'failed'),
    canResume: computed(() => props.state === 'resumeRequired'),
  }
}

const chatStateLabels: Record<string, string> = {
  idle: '准备就绪',
  creatingSession: '正在创建会话',
  loadingSession: '正在加载会话',
  deletingSession: '正在删除会话',
  preparing: '正在准备请求',
  streaming: '正在生成回复',
  evaluatingRun: '正在处理结果',
  approvalRequired: '等待工具审批',
  resumeRequired: '等待继续运行',
  resuming: '正在继续运行',
  retrying: '正在重试',
  canceling: '正在取消',
  clearing: '正在清空',
  canceled: '已取消',
  failed: '运行失败',
}

export function formatChatState(state: string): string {
  return chatStateLabels[state] || state
}

export type ChatApprovalItem = ToolApprovalRequest & {
  toolCallText: string
  permissionsText: string
  decisionText: string | null
  decided: boolean
  safetyLabel: string
  targets: { name: string; value: string }[]
}

export function approvalItem(
  approval: ToolApprovalRequest,
  status?: Extract<ToolApprovalStatus, 'approved' | 'denied'>,
): ChatApprovalItem {
  return {
    ...approval,
    toolCallText: JSON.stringify(approval.tool_call || {}, null, 2),
    permissionsText: approval.permissions?.join(', ') || '无',
    decisionText: status === 'approved'
      ? '已批准'
      : status === 'denied' ? '已拒绝' : null,
    decided: status === 'approved' || status === 'denied',
    safetyLabel: approval.safety_level === 'safe' ? '低风险'
      : approval.safety_level === 'sensitive' ? '敏感操作'
        : approval.safety_level === 'restricted' ? '受限操作' : '风险未知',
    targets: approvalTargets(approval.tool_call?.arguments),
  }
}

function approvalTargets(value: unknown): { name: string; value: string }[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  const labels: Record<string, string> = {
    project: '项目', path: '路径', file_path: '文件', directory: '目录',
    command: '命令', url: '地址', query: '查询', source: '来源', destination: '目标',
  }
  return Object.entries(value).flatMap(([key, target]) => (
    Object.hasOwn(labels, key) && typeof target === 'string'
      ? [{ name: labels[key] as string, value: target }] : []
  ))
}

export function formatChatError(error: unknown): string | null {
  if (!error) {
    return null
  }
  return error instanceof Error ? error.message : String(error)
}
