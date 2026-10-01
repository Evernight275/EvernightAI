import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type AgentRunState, type SkillDefinition } from '../src/api'
import { canRetryRun, runSkillIssues, skillErrorIssues } from '../src/domain/runSkills'
import { cancelForEditing, editableRunOptions, readRunDecisions, saveRunDecisions } from '../src/runtime/runEditor'

const run = (): AgentRunState => ({
  run_id: 'old', status: 'paused', skill_revisions: { style: 'v1' },
  request: { provider_id: 'main', model_id: 'model', context_id: 'ctx', skills: [{ skill_name: 'style' }] },
  pending_approval_requests: [{ approval_id: 'approval', tool_call_id: 'call', tool_name: 'write' }],
})
const skill = (revision = 'v1'): SkillDefinition => ({ name: 'style', description: 'Style', revision, is_enabled: true })

describe('run Skill conflicts', () => {
  it('distinguishes changed, disabled, deleted and legacy Skills', () => {
    expect(runSkillIssues(run(), [skill('v2')])).toEqual([{ reason: 'revision_changed', names: ['style'] }])
    expect(runSkillIssues(run(), [{ ...skill(), is_enabled: false }])[0]?.reason).toBe('disabled')
    expect(runSkillIssues(run(), [])[0]?.reason).toBe('deleted')
    expect(runSkillIssues({ ...run(), skill_revisions: null }, [skill()])[0]?.reason).toBe('revision_unavailable')
    expect(runSkillIssues({ ...run(), status: 'running', skill_revisions: null }, [skill()])).toEqual([])
    expect(runSkillIssues(run(), null)).toEqual([])
    expect(runSkillIssues(run(), [skill()])).toEqual([])
  })

  it('retains structured failure reasons after reload even if the Skill is restored', () => {
    const persisted = { ...run(), status: 'failed', metadata: { agent_runtime: {
      failure_type: 'SkillConflictError', failure_message: 'Versions unavailable',
      failure_detail: JSON.stringify({ reason: 'revision_unavailable', skill_names: ['style'] }),
    } } }
    expect(runSkillIssues(persisted, [skill()])).toEqual([{ reason: 'revision_unavailable', names: ['style'] }])
    expect(skillErrorIssues(new Error('SkillConflictError'), run())).toEqual([])
  })

  it.each(['failed', 'canceled'])('permits retry for %s runs', status => {
    expect(canRetryRun({ ...run(), status })).toBe(true)
  })
  it('excludes finished runs but permits unrecoverable paused runs', () => {
    expect(canRetryRun({ ...run(), status: 'finished' })).toBe(false)
    expect(canRetryRun(run())).toBe(false)
    expect(canRetryRun({ ...run(), metadata: { agent_runtime: { recovery_eligible: false } } })).toBe(true)
  })
})

describe('editing a conflicted run', () => {
  beforeEach(() => {
    const saved = new Map<string, string>()
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => saved.get(key) ?? null,
      setItem: (key: string, value: string) => saved.set(key, value),
      removeItem: (key: string) => saved.delete(key),
    })
    vi.stubGlobal('localStorage', { getItem: () => null })
    vi.stubGlobal('window', {})
  })
  afterEach(() => vi.unstubAllGlobals())

  it('restores only selections for current pending approvals of the same run', () => {
    saveRunDecisions(run(), { approval: 'approved', stale: 'denied' })
    expect(readRunDecisions(run())).toEqual({ approval: 'approved' })
    expect(readRunDecisions({ ...run(), run_id: 'new' })).toEqual({})
  })
  it('preserves approval choices when cancellation fails and clears them on success', async () => {
    saveRunDecisions(run(), { approval: 'approved' })
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(run())))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: 'Cancel unavailable' } }), { status: 503 }))
    vi.stubGlobal('fetch', fetcher)
    await expect(cancelForEditing('old')).rejects.toBeInstanceOf(ApiError)
    expect(readRunDecisions(run())).toEqual({ approval: 'approved' })
    fetcher.mockReset().mockResolvedValueOnce(new Response(JSON.stringify(run())))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...run(), status: 'canceled' })))
    const result = await cancelForEditing('old')
    expect(result.status).toBe('canceled')
    expect(readRunDecisions(run())).toEqual({})
    expect(fetcher.mock.calls.map(([path]) => path)).toEqual(['/agent-runs/old', '/agent-runs/old/cancel'])
  })
  it('refuses to edit if cancellation did not yield a terminal run', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response(JSON.stringify(run()))))
    await expect(cancelForEditing('old')).rejects.toThrow('运行尚未取消')
  })
  it('does not cancel under a changed identity after its initial state lookup', async () => {
    const controller = new AbortController()
    const fetcher = vi.fn(async () => {
      controller.abort()
      return new Response(JSON.stringify(run()))
    })
    vi.stubGlobal('fetch', fetcher)
    await expect(cancelForEditing('old', controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('preserves explicit options and removes old runtime and approval data', () => {
    expect(editableRunOptions({ ...run().request, tool_approvals: [{ approval_id: 'old', tool_call_id: 'old', status: 'approved' }],
      tools: [], max_tool_rounds: 2, metadata: { run_id: 'old', session_id: 'session', retry_of: 'source', agent_runtime: {}, note: 'keep' },
    })).toEqual({ tools: [], max_tool_rounds: 2, metadata: { note: 'keep' }, memory_query: undefined, recover_tool_errors: undefined, write_memory: undefined })
  })
})
