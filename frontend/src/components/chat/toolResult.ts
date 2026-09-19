export function toolResultSummary(text?: string): string {
  if (!text) return ''
  let value: unknown = text
  try {
    value = JSON.parse(text)
  } catch {
    /* Plain text is a valid tool result. */
  }
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>
    if (record.tool_call_result != null)
      return toolResultSummary(JSON.stringify(record.tool_call_result))
    const preview = [
      'error_message',
      'error',
      'message',
      'stdout',
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
      )
    if (preview !== undefined) value = preview
    else {
      const items = Object.values(record).find(Array.isArray)
      value = items ? `${items.length} 项结果` : Object.keys(record).join(' · ')
    }
    if (typeof record.exit_code === 'number') value = `退出码 ${record.exit_code} · ${value}`
  } else if (Array.isArray(value)) value = `${value.length} 项结果`
  const compact = String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
  return compact.length > 160 ? `${compact.slice(0, 160)}…` : compact
}
