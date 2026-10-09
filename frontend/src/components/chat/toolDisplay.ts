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
      blocks: TerminalBlock[];
      truncated: boolean;
    };

export interface TerminalSegment {
  text: string;
  color?: string;
  bold?: boolean;
  dim?: boolean;
}

export interface TerminalBlock {
  stream: 'stdout' | 'stderr';
  text: string;
  segments: TerminalSegment[];
}

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

const ansiColors = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'];

// Keeps the basic SGR colours and weights; every other escape is dropped.
export function terminalSegments(source: string): TerminalSegment[] {
  source = source.replace(/\x1b\][\s\S]*?(?:\x07|\x1b\\)/g, '');
  const segments: TerminalSegment[] = [];
  let style: Omit<TerminalSegment, 'text'> = {};
  const push = (text: string): void => {
    const visible = terminalText(text);
    if (visible) segments.push({ text: visible, ...style });
  };
  let offset = 0;
  for (const match of source.matchAll(/\x1b\[([0-9;]*)m/g)) {
    push(source.slice(offset, match.index));
    offset = match.index + match[0].length;
    const codes = (match[1] || '0').split(';').map(Number);
    for (let index = 0; index < codes.length; index++) {
      const code = codes[index] ?? 0;
      if (code === 0) style = {};
      else if (code === 1) style = { ...style, bold: true };
      else if (code === 2) style = { ...style, dim: true };
      else if (code === 22) style = { ...style, bold: undefined, dim: undefined };
      else if (code === 39) style = { ...style, color: undefined };
      else if (code >= 30 && code <= 37) style = { ...style, color: ansiColors[code - 30] };
      else if (code >= 90 && code <= 97)
        style = { ...style, color: 'bright-' + ansiColors[code - 90] };
      else if (code === 38 || code === 48) index += codes[index + 1] === 5 ? 2 : 4;
    }
  }
  push(source.slice(offset));
  return segments;
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
  const blocks: TerminalBlock[] = [];
  for (const stream of ['stdout', 'stderr'] as const) {
    const source = (value[stream] as string).slice(0, 100_000);
    if (source)
      blocks.push({ stream, text: terminalText(source), segments: terminalSegments(source) });
  }
  return {
    kind: 'terminal',
    command: terminalText(
      typeof value.shell_script === 'string' ? value.shell_script : commandText(value.command),
    ),
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

// The command a running tool was asked to execute, read from its call arguments.
export function pendingCommand(name: string, argumentsText?: string): string | undefined {
  if (!commandTools.has(name) || !argumentsText) return;
  try {
    const command = record(JSON.parse(argumentsText))?.command;
    if (typeof command === 'string' && command) return terminalText(command);
    if (
      Array.isArray(command) &&
      command.length &&
      command.every((argument) => typeof argument === 'string')
    )
      return terminalText(commandText(command));
  } catch {
    return;
  }
}
