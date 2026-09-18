import { requestJson } from './client'

export type WorkspaceDirectory = {
  root: string
  path: string
  entries: { name: string; path: string; is_directory: boolean }[]
  truncated: boolean
}
export function browseWorkspace(path = '.'): Promise<WorkspaceDirectory> {
  return requestJson(`/workspaces?path=${encodeURIComponent(path)}`)
}
export function createWorkspace(path: string, name: string): Promise<WorkspaceDirectory> {
  return requestJson('/workspaces', { method: 'POST', body: { path, name } })
}
