import { computed, type ComputedRef } from 'vue'
import type { WorkspaceIssue } from '../../domain/workspace'

export type ChatPrerequisitesProps = {
  state: string
  providerCount: number
  toolCount: number
  issues: WorkspaceIssue[]
}

export function useChatPrerequisites(
  props: ChatPrerequisitesProps,
): { notice: ComputedRef<string | null> } {
  return {
    notice: computed(() => prerequisiteNotice(props.state, props.providerCount)),
  }
}

export function prerequisiteNotice(state: string, providerCount: number): string | null {
  if (state === 'loading') {
    return '正在读取 Provider。'
  }
  if (state === 'offline') {
    return '后端不可用。'
  }
  if (state === 'unauthorized') {
    return '业务接口需要认证。'
  }
  if (providerCount === 0) {
    return '没有可用 Provider。'
  }
  return null
}
