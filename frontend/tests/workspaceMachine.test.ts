import { createActor, fromPromise, waitFor } from 'xstate'
import { describe, expect, it, vi } from 'vitest'
import {
  emptyWorkspaceSnapshot,
  type WorkspaceIssue,
  type WorkspaceLoadResult,
} from '../src/domain/workspace'
import { workspaceMachine } from '../src/state/workspaceMachine'

describe('workspaceMachine', () => {
  it('enters ready after every concept loads', async () => {
    const result = loadResult()
    const actor = actorWithLoader(async () => result)

    actor.start()
    actor.send({ type: 'START' })
    const snapshot = await waitFor(actor, (state) => state.matches('ready'))

    expect(snapshot.context.workspace).toBe(result.workspace)
    expect(snapshot.context.issues).toEqual([])
    expect(snapshot.context.connectionError).toBeNull()
    actor.stop()
  })

  it('enters degraded when one concept cannot load', async () => {
    const issue: WorkspaceIssue = {
      concept: 'knowledgeIndex',
      resource: 'memories',
      message: 'Forbidden',
      status: 403,
      errorType: 'PermissionDeniedError',
      cause: new Error('Forbidden'),
    }
    const actor = actorWithLoader(async () => loadResult([issue]))

    actor.start()
    actor.send({ type: 'START' })
    const snapshot = await waitFor(actor, (state) => state.matches('degraded'))

    expect(snapshot.context.issues).toEqual([issue])
    expect(snapshot.context.connectionError).toBeNull()
    actor.stop()
  })

  it('enters unauthorized when business APIs reject credentials', async () => {
    const issue: WorkspaceIssue = {
      concept: 'providerCatalog',
      resource: 'providers',
      message: 'Invalid API key',
      status: 401,
      errorType: 'AuthorizationError',
      cause: new Error('Invalid API key'),
    }
    const actor = actorWithLoader(async () => loadResult([issue]))

    actor.start()
    actor.send({ type: 'START' })
    const snapshot = await waitFor(actor, (state) => state.matches('unauthorized'))

    expect(snapshot.context.issues).toEqual([issue])
    actor.stop()
  })

  it('enters offline when the API connection fails', async () => {
    const error = new Error('API unavailable')
    const actor = actorWithLoader(async () => {
      throw error
    })

    actor.start()
    actor.send({ type: 'START' })
    const snapshot = await waitFor(actor, (state) => state.matches('offline'))

    expect(snapshot.context.connectionError).toBe(error)
    actor.stop()
  })

  it('cancels the current load when refreshed while loading', async () => {
    const signals: AbortSignal[] = []
    const loader = vi.fn(({ signal }: { signal: AbortSignal }) => {
      signals.push(signal)
      return new Promise<WorkspaceLoadResult>(() => undefined)
    })
    const actor = createActor(workspaceMachine.provide({
      actors: {
        loadWorkspace: fromPromise(loader),
      },
    }))

    actor.start()
    actor.send({ type: 'START' })
    await vi.waitFor(() => expect(loader).toHaveBeenCalledTimes(1))
    actor.send({ type: 'REFRESH' })
    await vi.waitFor(() => expect(loader).toHaveBeenCalledTimes(2))

    expect(signals[0]?.aborted).toBe(true)
    expect(signals[1]?.aborted).toBe(false)
    actor.stop()
  })
})

function actorWithLoader(loader: () => Promise<WorkspaceLoadResult>) {
  return createActor(workspaceMachine.provide({
    actors: {
      loadWorkspace: fromPromise(loader),
    },
  }))
}

function loadResult(issues: WorkspaceIssue[] = []): WorkspaceLoadResult {
  return {
    workspace: {
      ...emptyWorkspaceSnapshot(),
      loadedAt: '2026-08-22T00:00:00.000Z',
    },
    issues,
  }
}
