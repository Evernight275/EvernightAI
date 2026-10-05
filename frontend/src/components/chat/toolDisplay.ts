export interface DiffLine {
  kind: 'header' | 'hunk' | 'added' | 'removed' | 'context' | 'note';
  text: string;
  oldLine?: number;
  newLine?: number;
}

export type ToolDisplay =
  | {
      kind: 'diff';
      path: string;
      lines: DiffLine[];
      added: number;
      removed: number;
      truncated: boolean;
      unavailable: boolean;
    }
  | {
      kind: 'terminal';
      command: string;
      directory: string;
      exitCode: number;
      blocks: { stream: 'stdout' | 'stderr'; text: string }[];
      truncated: boolean;
    };

const fileTools = new Set([
  'write_text_file',
  'append_text_file',
  'apply_text_patch',
  'write_json_file',
]);
const commandTools = new Set([
  'restricted_shell',
  'run_project_task',
  'git_status',
  'git_diff',
  'git_log',
  'git_show',
  'git_commit',
  'git_list_branches',
  'git_checkout_branch',
  'git_create_branch',
]);

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

export function diffLines(source: string): DiffLine[] {
  const rows = source.split('\n');
  if (rows.at(-1) === '') rows.pop();
  let oldLine = 0;
  let newLine = 0;
  let inHunk = false;
  return rows.map((text): DiffLine => {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      inHunk = true;
      return { kind: 'hunk', text };
    }
    const visible = text.endsWith('\r') ? text.slice(0, -1) + ' ␍' : text;
    if (inHunk && text.startsWith('+')) return { kind: 'added', text: visible, newLine: newLine++ };
    if (inHunk && text.startsWith('-'))
      return { kind: 'removed', text: visible, oldLine: oldLine++ };
    if (inHunk && text.startsWith(' '))
      return { kind: 'context', text: visible, oldLine: oldLine++, newLine: newLine++ };
    if (text.startsWith('diff --git ')) inHunk = false;
    return { kind: text.startsWith('\\') ? 'note' : 'header', text: visible };
  });
}

export function terminalText(source: string): string {
  return source
    .replace(/\x1b\][\s\S]*?(?:\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\r\n?/g, '\n')
    .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '');
}

export function commandText(command: string[]): string {
  return command
    .map((argument) =>
      /^[a-zA-Z0-9_./:=@+-]+$/.test(argument)
        ? argument
        : "'" + argument.replace(/'/g, "'\\''") + "'",
    )
    .join(' ');
}

export function toolDisplay(name: string, text?: string): ToolDisplay | undefined {
  if (!text) return;
  let value: Record<string, unknown> | undefined;
  try {
    value = record(JSON.parse(text));
    for (let depth = 0; depth < 8 && value?.tool_call_result != null; depth++)
      value = record(value.tool_call_result);
  } catch {
    return;
  }
  if (!value) return;
  if (fileTools.has(name) && typeof value.path === 'string') {
    if (typeof value.diff !== 'string' && typeof value.bytes_written !== 'number') return;
    const source = typeof value.diff === 'string' ? value.diff : '';
    const lines = diffLines(source.slice(0, 100_000));
    return {
      kind: 'diff',
      path: value.path,
      lines,
      added: lines.filter((line) => line.kind === 'added').length,
      removed: lines.filter((line) => line.kind === 'removed').length,
      truncated: value.diff_truncated === true || source.length > 100_000,
      unavailable: typeof value.diff !== 'string',
    };
  }
  if (
    !commandTools.has(name) ||
    !Array.isArray(value.command) ||
    !value.command.length ||
    !value.command.every((argument) => typeof argument === 'string') ||
    typeof value.returncode !== 'number' ||
    !Number.isInteger(value.returncode) ||
    typeof value.stdout !== 'string' ||
    typeof value.stderr !== 'string'
  )
    return;
  const blocks: { stream: 'stdout' | 'stderr'; text: string }[] = [];
  for (const stream of ['stdout', 'stderr'] as const) {
    const source = value[stream] as string;
    if (source) blocks.push({ stream, text: terminalText(source.slice(0, 100_000)) });
  }
  return {
    kind: 'terminal',
    command: terminalText(commandText(value.command)),
    directory:
      [value.working_directory, value.repository_directory, value.cwd].find(
        (directory): directory is string => typeof directory === 'string',
      ) ?? '',
    exitCode: value.returncode,
    blocks,
    truncated:
      value.truncated === true || value.stdout.length > 100_000 || value.stderr.length > 100_000,
  };
}
