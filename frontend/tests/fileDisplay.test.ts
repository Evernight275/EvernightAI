import { describe, expect, it } from 'vitest';
import { fileToolArtifactId, toolResultSummary } from '../src/components/chat/toolResult';

describe('file tool results', () => {
  const result = { type: 'file_display', artifact_id: 'a'.repeat(32), name: '图表.png' };

  it('restores file references from live and persisted tool result wrappers', () => {
    expect(fileToolArtifactId(JSON.stringify(result))).toBe(result.artifact_id);
    expect(
      fileToolArtifactId(JSON.stringify({ tool_call_result: { tool_call_result: result } })),
    ).toBe(result.artifact_id);
    expect(toolResultSummary(JSON.stringify({ tool_call_result: result }))).toBe('已展示 图表.png');
  });

  it('rejects malformed references and other tool result types', () => {
    for (const value of [
      undefined,
      'not json',
      '{}',
      JSON.stringify({ ...result, artifact_id: '../private' }),
      JSON.stringify({ ...result, type: 'image_generation' }),
    ])
      expect(fileToolArtifactId(value)).toBeUndefined();
  });
});
