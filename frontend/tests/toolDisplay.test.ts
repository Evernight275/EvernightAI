import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { describe, expect, it } from 'vitest';
import ChatInlineTool from '../src/components/chat/ChatInlineTool.vue';
import ChatToolDisplay from '../src/components/chat/ChatToolDisplay.vue';
import { diffLines, terminalText, toolDisplay } from '../src/components/chat/toolDisplay';

const diff =
  '--- a/note.txt\n+++ b/note.txt\n@@ -3,2 +3,2 @@\n-hello\n+<script>bad</script>\n same\n';
const fileResult = { path: 'note.txt', bytes_written: 30, diff, diff_truncated: false };
const commandResult = {
  command: ['python', '-c', "print('hello world')"],
  returncode: 1,
  stdout: 'first\n\nlast\n',
  stderr: '\x1b[31m<script>error</script>\x1b[0m\n',
  truncated: true,
};

describe('specialized tool displays', () => {
  it('parses saved and wrapped file results with real line numbers', () => {
    const display = toolDisplay(
      'write_text_file',
      JSON.stringify({ tool_call_result: fileResult }),
    );
    expect(display).toMatchObject({ kind: 'diff', path: 'note.txt', added: 1, removed: 1 });
    expect(diffLines(diff).slice(3)).toEqual([
      { kind: 'removed', text: '-hello', oldLine: 3 },
      { kind: 'added', text: '+<script>bad</script>', newLine: 3 },
      { kind: 'context', text: ' same', oldLine: 4, newLine: 4 },
    ]);
    expect(diffLines('@@ -1 +1 @@\n---old\n+++new\n')[1]?.kind).toBe('removed');
    expect(diffLines('@@ -1 +1 @@\n---old\n+++new\n')[2]?.kind).toBe('added');
  });

  it('does not invent a diff for old records or unavailable snapshots', () => {
    expect(toolDisplay('append_text_file', '{"path":"a","bytes_written":3}')).toMatchObject({
      kind: 'diff',
      unavailable: true,
      lines: [],
    });
    expect(
      toolDisplay('apply_text_patch', JSON.stringify({ ...fileResult, diff: '' })),
    ).toMatchObject({
      kind: 'diff',
      unavailable: false,
      lines: [],
    });
  });

  it('handles command arrays, exit status, output channels and terminal controls', () => {
    expect(toolDisplay('restricted_shell', JSON.stringify(commandResult))).toMatchObject({
      kind: 'terminal',
      exitCode: 1,
      truncated: true,
      command: String.raw`python -c 'print('\''hello world'\'')'`,
      blocks: [
        { stream: 'stdout', text: 'first\n\nlast\n' },
        { stream: 'stderr', text: '<script>error</script>\n' },
      ],
    });
    expect(terminalText('a\x1b]8;;https://example.com\x07b\x1b]8;;\x1b\\\r\nc\x00')).toBe('ab\nc');
    expect(
      toolDisplay('run_project_task', JSON.stringify({ ...commandResult, stdout: '', stderr: '' })),
    ).toMatchObject({ blocks: [] });
    expect(toolDisplay('git_status', JSON.stringify(commandResult))?.kind).toBe('terminal');
  });

  it('falls back for unrelated tools, malformed results and failures', () => {
    for (const source of ['null', '[]', 'oops', '{"error_message":"denied"}'])
      expect(toolDisplay('write_text_file', source)).toBeUndefined();
    expect(toolDisplay('other', JSON.stringify(fileResult))).toBeUndefined();
    expect(
      toolDisplay('restricted_shell', JSON.stringify({ ...commandResult, command: [3] })),
    ).toBeUndefined();
  });

  it('renders diff and terminal text safely, with distinct styles', async () => {
    const file = await renderToString(
      createSSRApp(ChatToolDisplay, {
        name: 'write_text_file',
        resultText: JSON.stringify(fileResult),
      }),
    );
    expect(file).toContain('tool-diff-line--added');
    expect(file).toContain('tool-diff-line--removed');
    expect(file).toContain('&lt;script&gt;bad&lt;/script&gt;');
    expect(file).not.toContain('<script>bad');
    const terminal = await renderToString(
      createSSRApp(ChatToolDisplay, {
        name: 'restricted_shell',
        resultText: JSON.stringify(commandResult),
      }),
    );
    expect(terminal).toContain('退出码 1');
    expect(terminal).toContain('tool-terminal-stderr');
    expect(terminal).toContain('&lt;script&gt;error&lt;/script&gt;');
    expect(terminal).toContain('输出过长，已截断');
    expect(terminal).not.toContain('\x1b');
  });

  it('only shows actual completed file changes and retains raw JSON', async () => {
    const activity = {
      callId: 'call',
      name: 'write_text_file',
      status: 'completed' as const,
      argumentsText: '{}',
      resultText: JSON.stringify(fileResult),
    };
    const completed = await renderToString(createSSRApp(ChatInlineTool, { activity }));
    expect(completed).toContain('aria-label="文件差异"');
    expect(completed).toContain('调用参数');
    expect(completed).toContain('调用结果');
    const failed = await renderToString(
      createSSRApp(ChatInlineTool, {
        activity: { ...activity, status: 'failed' },
      }),
    );
    expect(failed).not.toContain('aria-label="文件差异"');
    expect(failed).toContain('定位错误');
  });
});
