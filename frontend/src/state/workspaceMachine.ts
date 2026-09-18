import { assign, createActor, fromPromise, setup } from 'xstate'
import {
  emptyWorkspaceSnapshot,
  loadWorkspace,
  type WorkspaceIssue,
  type WorkspaceLoadResult,
  type WorkspaceSnapshot,
} from '../domain/workspace'

export type WorkspaceMachineContext = {
  workspace: WorkspaceSnapshot
  issues: WorkspaceIssue[]
  connectionError: unknown
}

export type WorkspaceMachineEvent =
  | { type: 'START' }
  | { type: 'REFRESH' }
  | { type: 'AUTH_CHANGED' }

export const workspaceMachine = setup({
  types: {
    context: {} as WorkspaceMachineContext,
    events: {} as WorkspaceMachineEvent,
  },
  actors: {
    loadWorkspace: fromPromise<WorkspaceLoadResult>(
      ({ signal }) => loadWorkspace(signal),
    ),
  },
}).createMachine({
  id: 'workspace',
  initial: 'idle',
  context: {
    workspace: emptyWorkspaceSnapshot(),
    issues: [],
    connectionError: null,
  },
  on: {
    AUTH_CHANGED: {
      target: ".loading",
      reenter: true,
      actions: assign({ workspace: () => emptyWorkspaceSnapshot(), issues: [], connectionError: null }),
    },
  },
  states: {
    idle: {
      on: {
        START: 'loading',
      },
    },
    loading: {
      invoke: {
        id: 'loadWorkspace',
        src: 'loadWorkspace',
        onDone: [
          {
            guard: ({ event }) => event.output.issues.some((issue) => issue.status === 401),
            target: 'unauthorized',
            actions: assign({
              workspace: ({ event }) => event.output.workspace,
              issues: ({ event }) => event.output.issues,
              connectionError: null,
            }),
          },
          {
            guard: ({ event }) => event.output.issues.length > 0,
            target: 'degraded',
            actions: assign({
              workspace: ({ event }) => event.output.workspace,
              issues: ({ event }) => event.output.issues,
              connectionError: null,
            }),
          },
          {
            target: 'ready',
            actions: assign({
              workspace: ({ event }) => event.output.workspace,
              issues: ({ event }) => event.output.issues,
              connectionError: null,
            }),
          },
        ],
        onError: {
          target: 'offline',
          actions: assign({
            connectionError: ({ event }) => event.error,
          }),
        },
      },
      on: {
        REFRESH: {
          target: 'loading',
          reenter: true,
        },
      },
    },
    ready: {
      on: {
        REFRESH: 'loading',
      },
    },
    degraded: {
      on: {
        REFRESH: 'loading',
      },
    },
    unauthorized: {
      on: {
        REFRESH: 'loading',
      },
    },
    offline: {
      on: {
        REFRESH: 'loading',
      },
    },
  },
})

export const workspaceActor = createActor(workspaceMachine)
