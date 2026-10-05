export function imageToolRecordId(text?: string): string | undefined {
  if (!text) return;
  try {
    const parsed = JSON.parse(text);
    const value = parsed?.tool_call_result ?? parsed;
    if (
      value?.type === 'image_generation' &&
      typeof value.record_id === 'string' &&
      /^[a-f0-9]{32}$/.test(value.record_id)
    )
      return value.record_id;
  } catch {
    /* Other tool results need no image preview. */
  }
}

export function toolResultSummary(text?: string): string {
  if (!text) return '';
  let value: unknown = text;
  try {
    value = JSON.parse(text);
  } catch {
    /* Plain text is a valid tool result. */
  }
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    if (record.tool_call_result != null)
      return toolResultSummary(JSON.stringify(record.tool_call_result));
    if (record.type === 'image_generation' && Array.isArray(record.images))
      return `已生成 ${record.images.length} 张图片`;
    const preview = [
      'error_message',
      'error',
      'message',
      'stdout',
      'stderr',
      'content',
      'text',
      'output',
      'result',
    ]
      .map((key) => record[key])
      .find(
        (item) =>
          (typeof item === 'string' && item.trim()) ||
          typeof item === 'number' ||
          typeof item === 'boolean',
      );
    if (typeof record.path === 'string' && typeof record.bytes_written === 'number')
      value = `已写入 ${record.path}（${record.bytes_written} 字节）`;
    else if (preview !== undefined) value = preview;
    else if (Array.isArray(record.command) && typeof record.returncode === 'number')
      value = '命令未产生输出';
    else {
      const items = Object.values(record).find(Array.isArray);
      value = items ? `${items.length} 项结果` : Object.keys(record).join(' · ');
    }
    const exitCode = record.exit_code ?? record.returncode;
    if (typeof exitCode === 'number') value = `退出码 ${exitCode} · ${value}`;
  } else if (Array.isArray(value)) value = `${value.length} 项结果`;
  const compact = String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim();
  return compact.length > 160 ? `${compact.slice(0, 160)}…` : compact;
}
