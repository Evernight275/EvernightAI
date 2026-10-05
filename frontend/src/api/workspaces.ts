import { requestJson } from './client';

export type WorkspaceDirectory = {
  root: string;
  path: string;
  entries: { name: string; path: string; is_directory: boolean }[];
  truncated: boolean;
  parent?: string | null;
};
export type WorkspaceProject = { name: string; path: string };
export function listWorkspaceProjects(): Promise<WorkspaceProject[]> {
  return requestJson('/workspaces/projects');
}
export function addWorkspaceProject(path: string): Promise<WorkspaceDirectory> {
  return requestJson('/workspaces/projects', { method: 'POST', body: { path } });
}
export function browseWorkspace(path = '.'): Promise<WorkspaceDirectory> {
  return requestJson(`/workspaces?path=${encodeURIComponent(path)}`);
}
export function createWorkspace(path: string, name: string): Promise<WorkspaceDirectory> {
  return requestJson('/workspaces', { method: 'POST', body: { path, name } });
}
