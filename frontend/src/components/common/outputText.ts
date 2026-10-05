export type OutputPart = { text: string; match?: number };

export function outputParts(source: string, query: string): OutputPart[] {
  if (!query) return [{ text: source }];
  const parts: OutputPart[] = [];
  const pattern = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'giu');
  let offset = 0;
  let match = 0;
  for (const found of source.matchAll(pattern)) {
    const start = found.index;
    if (start > offset) parts.push({ text: source.slice(offset, start) });
    parts.push({ text: found[0], match: match++ });
    offset = start + found[0].length;
  }
  if (offset < source.length) parts.push({ text: source.slice(offset) });
  return parts;
}
