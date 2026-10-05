import { computed, type ComputedRef } from 'vue';
import type { ToolApprovalRequest, ToolApprovalStatus, ToolDefinition } from '../../api';
import type { ApprovalStatuses } from '../../runtime/chatRuntime';
import { commandText } from './toolDisplay';

export type ChatRequestStatusProps = {
  state: string;
  error: unknown;
  workspaceNotice?: string | null;
  pendingApprovals: ToolApprovalRequest[];
  approvalStatuses: ApprovalStatuses;
  skillConflict?: boolean;
  retryBlocked?: boolean;
  retryTools?: string[];
  runId?: string | null;
  canReplyOnly?: boolean;
};

export type ChatRequestStatusEmits = {
  retry: [];
  resume: [];
  details: [];
  replyOnly: [];
};

export function useChatRequestStatus(props: ChatRequestStatusProps): {
  visible: ComputedRef<boolean>;
  errorMessage: ComputedRef<string | null>;
  canRetry: ComputedRef<boolean>;
  canResume: ComputedRef<boolean>;
} {
  const canRetry = computed(
    () => props.state === 'failed' && !props.skillConflict && !props.retryBlocked,
  );
  const canResume = computed(
    () =>
      !props.skillConflict &&
      (props.state === 'resumeRequired' ||
        (props.state === 'approvalRequired' &&
          props.pendingApprovals.every((item) => props.approvalStatuses[item.approval_id]))),
  );
  return {
    visible: computed(
      () =>
        canRetry.value || canResume.value || Boolean(props.error) || Boolean(props.workspaceNotice),
    ),
    errorMessage: computed(() => formatChatError(props.error)),
    canRetry,
    canResume,
  };
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
  recovering: '正在恢复运行进度',
  canceling: '正在取消',
  clearing: '正在清空',
  canceled: '已取消',
  failed: '运行失败',
};

export function formatChatState(state: string): string {
  return chatStateLabels[state] || state;
}

export type ChatApprovalItem = ToolApprovalRequest & {
  toolCallText: string;
  permissionsText: string;
  decisionText: string | null;
  decided: boolean;
  safetyLabel: string;
  targets: { name: string; value: string }[];
};

export function approvalItem(
  approval: ToolApprovalRequest,
  status?: Extract<ToolApprovalStatus, 'approved' | 'denied'>,
  tool?: ToolDefinition,
): ChatApprovalItem {
  return {
    ...approval,
    toolCallText: JSON.stringify(approval.tool_call || {}, null, 2),
    permissionsText: approval.permissions?.join(', ') || '无',
    decisionText: status === 'approved' ? '已批准' : status === 'denied' ? '已拒绝' : null,
    decided: status === 'approved' || status === 'denied',
    safetyLabel:
      approval.safety_level === 'safe'
        ? '低风险'
        : approval.safety_level === 'sensitive'
          ? '敏感操作'
          : approval.safety_level === 'restricted'
            ? '受限操作'
            : '风险未知',
    targets: [
      ...(typeof approval.metadata?.working_directory === 'string'
        ? [{ name: '工作文件夹', value: approval.metadata.working_directory }]
        : []),
      ...(!approval.metadata?.working_directory &&
      typeof tool?.metadata?.root_directory === 'string'
        ? [{ name: '默认文件根目录', value: tool.metadata.root_directory }]
        : []),
      ...(!approval.metadata?.working_directory &&
      typeof tool?.metadata?.working_directory === 'string'
        ? [{ name: '默认命令目录', value: tool.metadata.working_directory }]
        : []),
      ...approvalTargets(approval.tool_call?.arguments),
      ...projectTaskTargets(approval, tool),
    ],
  };
}

function projectTaskTargets(
  approval: ToolApprovalRequest,
  tool?: ToolDefinition,
): { name: string; value: string }[] {
  if (approval.tool_name !== 'run_project_task' || !tool) return [];
  const args = approval.tool_call?.arguments as Record<string, unknown> | undefined;
  if (!args || typeof args.task !== 'string') return [];
  const commands = tool.metadata?.task_commands as Record<string, unknown> | undefined;
  const projects = tool.metadata?.project_task_commands as
    Record<string, Record<string, unknown>> | undefined;
  const roots = tool.metadata?.project_roots as Record<string, unknown> | undefined;
  const project = typeof args.project === 'string' ? args.project : '';
  const command = projects?.[project]?.[args.task] ?? commands?.[args.task];
  const directory = roots?.[project] ?? tool.metadata?.working_directory;
  return [
    ...(Array.isArray(command) && command.every((part) => typeof part === 'string')
      ? [{ name: '配置命令', value: commandText(command) }]
      : []),
    ...(typeof directory === 'string' ? [{ name: '任务执行目录', value: directory }] : []),
  ];
}

function approvalTargets(value: unknown): { name: string; value: string }[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  const labels: Record<string, string> = {
    project: '项目',
    path: '路径',
    file_path: '文件',
    directory: '目录',
    cwd: '命令目录',
    task: '项目任务',
    command: '命令',
    source_path: '来源路径',
    destination_path: '目标路径',
    provider_id: '生图服务',
    model_id: '生图模型',
    n: '图片数量',
    overwrite: '覆盖已有文件',
    recursive: '递归操作',
    url: '地址',
    query: '查询',
    source: '来源',
    destination: '目标',
  };
  return Object.entries(value).flatMap(([key, target]) =>
    !Object.hasOwn(labels, key)
      ? []
      : key === 'command' &&
          Array.isArray(target) &&
          target.every((part) => typeof part === 'string')
        ? [{ name: '命令', value: commandText(target) }]
        : typeof target === 'string' || typeof target === 'number' || typeof target === 'boolean'
          ? [
              {
                name: labels[key] as string,
                value: typeof target === 'boolean' ? (target ? '是' : '否') : String(target),
              },
            ]
          : [],
  );
}

export function formatChatError(error: unknown): string | null {
  if (!error) {
    return null;
  }
  return error instanceof Error ? error.message : String(error);
}
