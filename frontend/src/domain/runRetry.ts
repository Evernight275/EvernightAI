import type { AgentRunState } from '../api';
import type { ChatSubmission } from './chat';

export function retryToolNames(run: AgentRunState | null): string[] {
  if (!run || !['failed', 'canceled', 'paused'].includes(run.status || '')) return [];
  const calls = [
    ...(run.trace || [])
      .filter((event) =>
        ['tool_started', 'tool_completed', 'tool_failed'].includes(event.event_type),
      )
      .map((event) => event.tool_call),
    ...(run.steps || [])
      .filter((step) => ['tool', 'tool_error'].includes(step.step_type))
      .map((step) => step.tool_call),
  ];
  return [
    ...new Set(
      calls.flatMap((call) => {
        if (!call) return [];
        const name = call.tool_call.name || call.tool_call.tool_name;
        return [typeof name === 'string' ? name : '未知工具'];
      }),
    ),
  ];
}

export function replyOnlySubmission(run: AgentRunState): ChatSubmission {
  const events = run.trace?.length
    ? run.trace.filter((event) =>
        ['tool_started', 'tool_completed', 'tool_failed'].includes(event.event_type),
      )
    : (run.steps || []).filter((step) => ['tool', 'tool_error'].includes(step.step_type));
  const results = events.map((event) => ({
    tool_call: event.tool_call,
    result: event.tool_result,
    error_type: event.error_type,
    error_message: event.error_message,
    ...('event_type' in event ? { status: event.event_type } : { status: event.step_type }),
  }));
  const text = '根据已保存的工具结果继续回复';
  return {
    providerId: run.request.provider_id,
    modelId: run.request.model_id,
    workingDirectory: run.request.working_directory || undefined,
    text,
    messages: [
      ...(run.request.messages || []),
      {
        role: 'user',
        content: [
          {
            type: 'text',
            text: `请根据原请求和以下已保存的执行记录继续回答。此次只能回复，不能执行工具。已完成的结果直接使用；只有开始记录而没有结果的操作，请说明结果未确认。\n${JSON.stringify(results)}`,
          },
        ],
      },
    ],
    runOptions: {
      tools: [],
      max_tool_rounds: 0,
      write_memory: false,
      metadata: { reply_only_of: run.run_id, chat_display_text: text },
    },
  };
}
