import highlighter from 'highlight.js/lib/core';
import json from 'highlight.js/lib/languages/json';

if (!highlighter.getLanguage('json')) highlighter.registerLanguage('json', json);

export function renderJson(source: string): string {
  if (source.length <= 100_000) {
    try {
      JSON.parse(source);
      return highlighter.highlight(source, { language: 'json', ignoreIllegals: true }).value;
    } catch {
      // Plain errors and partial arguments remain readable while streaming.
    }
  }
  return source
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
