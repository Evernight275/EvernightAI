import type { Content } from './api'

export function textPart(message?: Content | null): string {
  const parts = Array.isArray(message?.content) ? message.content : []
  const text = parts.find((part) => part?.type === 'text' && part.text)?.text
  return text || ''
}

export function shortId(value?: string | null): string {
  if (!value) {
    return '未命名'
  }

  return value.length > 18 ? `${value.slice(0, 18)}...` : value
}

export function formatStatus(status?: string | null): string {
  const labels: Record<string, string> = {
    active: '活跃',
    archived: '归档',
    running: '运行中',
    paused: '暂停',
    finished: '完成',
    failed: '失败',
    user: '用户',
    assistant: 'Agent',
    system: '系统',
    tool: '工具',
    safe: '安全',
    sensitive: '敏感',
    restricted: '受限',
  }

  return status ? labels[status] || status : '未知'
}

export function formatTime(value?: string | null): string {
  if (!value) {
    return '-'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }

  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}
