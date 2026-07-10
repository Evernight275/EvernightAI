export type ViewKey =
  | 'workbench'
  | 'chat'
  | 'tools'
  | 'runs'
  | 'analytics'
  | 'agents'
  | 'memories'
  | 'logs'

export type ViewMeta = {
  title: string
  description: string
}

export const viewMeta: Record<ViewKey, ViewMeta> = {
  workbench: {
    title: '主页',
    description: '左侧是重要入口，上方是当前项目相关上下文，主体看会话、工具与执行流',
  },
  chat: {
    title: '聊天',
    description: '选择会话、查看上下文，并向当前会话发送消息',
  },
  tools: {
    title: '工具列表',
    description: '查看后端 runtime 已注册的工具和审批要求',
  },
  runs: {
    title: '运行队列',
    description: '查看 Agent run 状态、模型、工具轮次和最近输出',
  },
  analytics: {
    title: '数据统计',
    description: '查看 Agent、会话、工具调用和记忆写入的运行统计',
  },
  agents: {
    title: '模型提供商配置',
    description: '查看已注册 provider，并主动拉取每个 provider 暴露的模型',
  },
  memories: {
    title: '记忆库',
    description: '查看持久记忆入口，后续会接入查询和编辑',
  },
  logs: {
    title: '日志',
    description: '查看运行事件和系统日志入口',
  },
}

export const viewKeys = Object.keys(viewMeta) as ViewKey[]
