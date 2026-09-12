import * as api from '../../api'

export type ManagementField = { key: string; label: string; value?: string; optional?: boolean; json?: boolean }
export type ManagementAction = { id: string; label: string; group: string; fields: ManagementField[]; confirmation?: string; run: (values: Record<string, string>) => Promise<unknown> }
const id = (key: string, label: string): ManagementField => ({ key, label })
const body = (value: unknown): ManagementField => ({ key: 'body', label: '高级参数（JSON）', json: true, value: JSON.stringify(value, null, 2) })
function parse<T>(v: Record<string, string>): T {
  const result: unknown = JSON.parse(v.body || '{}')
  if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('参数必须是 JSON 对象')
  return result as T
}
const context = id('context', '上下文 ID')
const session = id('session', '会话 ID')
const run = id('run', '运行 ID')
const source = id('source', '数据源 ID')
const skill = id('skill', '技能名称')
const provider = id('provider', '服务 ID')
const message = { role: 'user', content: [{ type: 'text', text: '' }] }
const chatRequest = { model_id: '', messages: [message] }

export const managementActions: ManagementAction[] = [
  { id: 'select-memory', group: '记忆', label: '高级记忆选择预览', fields: [body({ text: '', scope: 'global', include_disabled: false, include_expired: false, deduplicate: true, limit: 20 })], run: v => api.selectMemories(parse(v)) },
  { id: 'direct-chat', group: '模型调试', label: '直接聊天', fields: [provider, body(chatRequest)], run: v => api.chat({ provider_id: v.provider!, request: parse(v) }) },
  { id: 'context-chat', group: '模型调试', label: '使用上下文聊天', fields: [provider, context, body(chatRequest)], run: v => api.chatWithContext({ ...parse<api.ChatWithContextRequest>(v), provider_id: v.provider!, context_id: v.context! }) },
  { id: 'session-chat', group: '模型调试', label: '使用会话聊天', fields: [session, body({ messages: [message] })], run: v => api.chatWithSession(v.session!, parse(v)) },
  { id: 'session-agent', group: '模型调试', label: '启动会话任务', fields: [session, body({ messages: [message], pause_on_approval: true })], run: v => api.startSessionAgentRun(v.session!, { ...parse<api.SessionAgentRunRequest>(v), pause_on_approval: true }) },
  { id: 'contexts', group: '上下文', label: '查看上下文列表', fields: [], run: () => api.listContexts() },
  { id: 'context', group: '上下文', label: '查看上下文消息', fields: [context], run: v => api.getContext(v.context!) },
  { id: 'create-context', group: '上下文', label: '创建上下文', fields: [body({ context_id: '', messages: [] })], run: v => api.createContext(parse(v)) },
  { id: 'append-context', group: '上下文', label: '追加消息', fields: [context, body(message)], run: v => api.appendContextMessage(v.context!, parse(v)) },
  { id: 'replace-context', group: '上下文', label: '替换上下文消息', fields: [context, body({ messages: [] })], confirmation: '此操作会替换全部上下文消息。确认继续？', run: v => api.replaceContext(v.context!, { ...parse<api.Context>(v), context_id: v.context! }) },
  { id: 'delete-context', group: '上下文', label: '删除上下文', fields: [context], confirmation: '永久删除这个上下文？关联会话可能无法继续使用它。', run: v => api.deleteContext(v.context!) },
  { id: 'preview-context', group: '上下文', label: '预览模型可见消息', fields: [context, body({ model_id: '', messages: [], skills: [] })], run: v => api.composeContextPreview(v.context!, parse(v)) },
  { id: 'sessions', group: '会话', label: '查看全部会话', fields: [], run: () => api.listSessions() },
  { id: 'session', group: '会话', label: '查看会话详情', fields: [session], run: v => api.getSession(v.session!) },
  { id: 'archive', group: '会话', label: '归档会话', fields: [session], confirmation: '归档这段会话？', run: v => api.archiveSession(v.session!) },
  { id: 'rename', group: '会话', label: '修改会话标题', fields: [session, id('title', '新标题')], run: async v => api.replaceSession(v.session!, { ...await api.getSession(v.session!), title: v.title! }) },
  { id: 'restore', group: '会话', label: '恢复归档会话', fields: [session], run: async v => api.replaceSession(v.session!, { ...await api.getSession(v.session!), status: 'active' }) },
  { id: 'sources', group: '数据分析', label: '查看数据源', fields: [], run: () => api.listDataSources() },
  { id: 'source', group: '数据分析', label: '查看数据源结构', fields: [source], run: async v => ({ source: await api.getDataSource(v.source!), fields: await api.listDataFields(v.source!), metrics: await api.listDataMetrics(v.source!) }) },
  { id: 'statistics', group: '数据分析', label: '查询统计', fields: [body({ source_id: '', metrics: [], dimensions: [], filters: [], limit: 20 })], run: v => api.runDataStatistics(parse(v)) },
  { id: 'analysis', group: '数据分析', label: '分析数据', fields: [source, id('question', '分析问题')], run: v => api.analyzeData({ source_id: v.source!, question: v.question! }) },
  { id: 'tools', group: '工具与技能', label: '查看工具与权限', fields: [], run: () => api.listTools() },
  { id: 'skills', group: '工具与技能', label: '查看技能', fields: [], run: () => api.listSkills() },
  { id: 'skill', group: '工具与技能', label: '查看技能参数', fields: [skill], run: v => api.getSkill(v.skill!) },
  { id: 'render', group: '工具与技能', label: '预览技能提示词', fields: [skill, body({ variables: {} })], run: v => api.renderSkill(v.skill!, parse(v)) },
  { id: 'skill-supports', group: '工具与技能', label: '检查技能能力', fields: [skill, { key: 'capability', label: '能力（chat / tool_use / memory / context / agent / streaming）', value: 'chat' }], run: v => api.skillSupports(v.skill!, v.capability as api.SkillCapability) },
  { id: 'model', group: '模型', label: '查看模型详情', fields: [provider, id('model', '模型 ID')], run: v => api.getProviderModel(v.provider!, v.model!) },
  { id: 'provider-supports', group: '模型', label: '检查服务能力', fields: [provider, { key: 'capability', label: '能力（chat / tool_call / image_recognition 等）', value: 'chat' }], run: v => api.providerSupports(v.provider!, v.capability as api.ProviderModelCapability) },
  { id: 'runs', group: '运行记录', label: '查看运行列表', fields: [], run: () => api.listAgentRuns() },
  { id: 'run', group: '运行记录', label: '查看运行详情', fields: [run], run: v => api.getAgentRun(v.run!) },
  { id: 'trace', group: '运行记录', label: '查看执行轨迹', fields: [run], run: v => api.listAgentTrace(v.run!) },
  { id: 'attempts', group: '运行记录', label: '查看工具执行记录', fields: [run], run: v => api.listAgentRunToolExecutions(v.run!) },
  { id: 'pause', group: '运行记录', label: '暂停运行', fields: [run], confirmation: '暂停该运行？', run: v => api.pauseAgentRun(v.run!) },
  { id: 'cancel', group: '运行记录', label: '取消运行', fields: [run], confirmation: '取消该运行？', run: v => api.cancelAgentRun(v.run!) },
  { id: 'resolve', group: '运行记录', label: '处理未确定的工具执行', fields: [run, id('call', '工具调用 ID'), { key: 'attempt', label: '尝试次数', value: '1' }, body({ resolution: 'confirm_completed', result: {}, reason: '' })], confirmation: '请核对工具执行记录。确认完成或允许重试可能影响外部操作。继续？', run: v => { const n = Number(v.attempt); if (!Number.isInteger(n) || n < 1) throw new Error('尝试次数必须是正整数'); return api.resolveAgentRunToolExecution(v.run!, v.call!, n, parse(v)) } },
  { id: 'logs', group: '日志', label: '查看服务日志', fields: [{ key: 'limit', label: '条数', value: '100' }, { key: 'after', label: '从序号之后加载', optional: true }], run: v => { const n = Number(v.limit); if (!Number.isInteger(n) || n < 1) throw new Error('条数必须是正整数'); return api.listLogs({ limit: n, after: v.after ? Number(v.after) : undefined }) } },
  { id: 'clear-logs', group: '日志', label: '清除服务日志', fields: [], confirmation: '这会清除服务端日志。确认继续？', run: () => api.clearLogs() },
  { id: 'readiness', group: '服务状态', label: '检查服务就绪状态', fields: [], run: () => api.getReadiness() },
  { id: 'health', group: '服务状态', label: '检查服务存活', fields: [], run: () => api.getHealth() },
]
