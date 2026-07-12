<script setup lang="ts">
import { computed } from 'vue'

type IconNode = {
  tag: 'path' | 'rect' | 'circle' | 'ellipse' | 'line' | 'polyline' | 'polygon'
  attrs: Record<string, string | number>
}

const props = defineProps<{
  name: string
}>()

const icons: Record<string, IconNode[]> = {
  activity: [
    { tag: 'path', attrs: { d: 'M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2' } },
  ],
  'alert-triangle': [
    { tag: 'path', attrs: { d: 'm21.73 18-8-14a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3' } },
    { tag: 'path', attrs: { d: 'M12 9v4' } },
    { tag: 'path', attrs: { d: 'M12 17h.01' } },
  ],
  bot: [
    { tag: 'path', attrs: { d: 'M12 8V4H8' } },
    { tag: 'rect', attrs: { width: 16, height: 12, x: 4, y: 8, rx: 2 } },
    { tag: 'path', attrs: { d: 'M2 14h2' } },
    { tag: 'path', attrs: { d: 'M20 14h2' } },
    { tag: 'path', attrs: { d: 'M15 13v2' } },
    { tag: 'path', attrs: { d: 'M9 13v2' } },
  ],
  clock: [
    { tag: 'circle', attrs: { cx: 12, cy: 12, r: 10 } },
    { tag: 'polyline', attrs: { points: '12 6 12 12 16 14' } },
  ],
  'chevron-down': [
    { tag: 'path', attrs: { d: 'm6 9 6 6 6-6' } },
  ],
  'chevron-left': [
    { tag: 'path', attrs: { d: 'm15 18-6-6 6-6' } },
  ],
  'chevron-right': [
    { tag: 'path', attrs: { d: 'm9 18 6-6-6-6' } },
  ],
  check: [
    { tag: 'path', attrs: { d: 'm20 6-11 11-5-5' } },
  ],
  'check-circle': [
    { tag: 'path', attrs: { d: 'M22 11.08V12a10 10 0 1 1-5.93-9.14' } },
    { tag: 'path', attrs: { d: 'm22 4-10 10.01-3-3' } },
  ],
  'chart-column': [
    { tag: 'path', attrs: { d: 'M3 3v18h18' } },
    { tag: 'path', attrs: { d: 'M18 17V9' } },
    { tag: 'path', attrs: { d: 'M13 17V5' } },
    { tag: 'path', attrs: { d: 'M8 17v-3' } },
  ],
  copy: [
    { tag: 'rect', attrs: { width: 14, height: 14, x: 8, y: 8, rx: 2 } },
    { tag: 'path', attrs: { d: 'M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2' } },
  ],
  cpu: [
    { tag: 'rect', attrs: { width: 16, height: 16, x: 4, y: 4, rx: 2 } },
    { tag: 'rect', attrs: { width: 6, height: 6, x: 9, y: 9, rx: 1 } },
    { tag: 'path', attrs: { d: 'M9 1v3' } },
    { tag: 'path', attrs: { d: 'M15 1v3' } },
    { tag: 'path', attrs: { d: 'M9 20v3' } },
    { tag: 'path', attrs: { d: 'M15 20v3' } },
    { tag: 'path', attrs: { d: 'M20 9h3' } },
    { tag: 'path', attrs: { d: 'M20 14h3' } },
    { tag: 'path', attrs: { d: 'M1 9h3' } },
    { tag: 'path', attrs: { d: 'M1 14h3' } },
  ],
  database: [
    { tag: 'ellipse', attrs: { cx: 12, cy: 5, rx: 9, ry: 3 } },
    { tag: 'path', attrs: { d: 'M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5' } },
    { tag: 'path', attrs: { d: 'M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3' } },
  ],
  'file-text': [
    { tag: 'path', attrs: { d: 'M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5z' } },
    { tag: 'polyline', attrs: { points: '14 2 14 8 20 8' } },
    { tag: 'path', attrs: { d: 'M8 13h8' } },
    { tag: 'path', attrs: { d: 'M8 17h8' } },
    { tag: 'path', attrs: { d: 'M8 9h2' } },
  ],
  inbox: [
    { tag: 'polyline', attrs: { points: '22 12 16 12 14 15 10 15 8 12 2 12' } },
    { tag: 'path', attrs: { d: 'm5.45 5.11-3.2 6.4A2 2 0 0 0 2 12.4V19a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6.6a2 2 0 0 0-.25-.89l-3.2-6.4A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z' } },
  ],
  info: [
    { tag: 'circle', attrs: { cx: 12, cy: 12, r: 10 } },
    { tag: 'path', attrs: { d: 'M12 16v-4' } },
    { tag: 'path', attrs: { d: 'M12 8h.01' } },
  ],
  'image-plus': [
    { tag: 'rect', attrs: { x: 3, y: 3, width: 18, height: 18, rx: 2 } },
    { tag: 'circle', attrs: { cx: 9, cy: 9, r: 2 } },
    { tag: 'path', attrs: { d: 'm21 15-5-5L5 21' } },
    { tag: 'path', attrs: { d: 'M17 3v6' } },
    { tag: 'path', attrs: { d: 'M14 6h6' } },
  ],
  'key-round': [
    { tag: 'path', attrs: { d: 'M21 2l-9.6 9.6' } },
    { tag: 'circle', attrs: { cx: 7.5, cy: 15.5, r: 5.5 } },
    { tag: 'path', attrs: { d: 'm15.5 7.5 3 3' } },
    { tag: 'path', attrs: { d: 'm18 5 1.5 1.5' } },
  ],
  'layout-dashboard': [
    { tag: 'rect', attrs: { width: 7, height: 9, x: 3, y: 3, rx: 1 } },
    { tag: 'rect', attrs: { width: 7, height: 5, x: 14, y: 3, rx: 1 } },
    { tag: 'rect', attrs: { width: 7, height: 9, x: 14, y: 12, rx: 1 } },
    { tag: 'rect', attrs: { width: 7, height: 5, x: 3, y: 16, rx: 1 } },
  ],
  'message-square': [
    { tag: 'path', attrs: { d: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z' } },
  ],
  'message-square-plus': [
    { tag: 'path', attrs: { d: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7' } },
    { tag: 'path', attrs: { d: 'M12 7v6' } },
    { tag: 'path', attrs: { d: 'M9 10h6' } },
  ],
  'message-circle': [
    { tag: 'path', attrs: { d: 'M21 15a4 4 0 0 1-4 4H8l-5 3 1.7-5.1A9 9 0 1 1 21 15z' } },
  ],
  pause: [
    { tag: 'rect', attrs: { x: 14, y: 4, width: 4, height: 16, rx: 1 } },
    { tag: 'rect', attrs: { x: 6, y: 4, width: 4, height: 16, rx: 1 } },
  ],
  pencil: [
    { tag: 'path', attrs: { d: 'M21.17 6.83a2.83 2.83 0 0 0-4-4L3 17v4h4Z' } },
    { tag: 'path', attrs: { d: 'm15 5 4 4' } },
  ],
  play: [
    { tag: 'polygon', attrs: { points: '6 3 20 12 6 21 6 3' } },
  ],
  plus: [
    { tag: 'path', attrs: { d: 'M5 12h14' } },
    { tag: 'path', attrs: { d: 'M12 5v14' } },
  ],
  'rotate-ccw': [
    { tag: 'path', attrs: { d: 'M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8' } },
    { tag: 'path', attrs: { d: 'M3 3v5h5' } },
  ],
  'scroll-text': [
    { tag: 'path', attrs: { d: 'M15 12h-5' } },
    { tag: 'path', attrs: { d: 'M15 8h-5' } },
    { tag: 'path', attrs: { d: 'M19 17V5a2 2 0 0 0-2-2H7' } },
    { tag: 'path', attrs: { d: 'M8 21h8a2 2 0 0 0 2-2v-1a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v1a2 2 0 0 0 2 2h2Z' } },
    { tag: 'path', attrs: { d: 'M7 3a2 2 0 0 0-2 2v11' } },
  ],
  send: [
    { tag: 'path', attrs: { d: 'm22 2-7 20-4-9-9-4Z' } },
    { tag: 'path', attrs: { d: 'M22 2 11 13' } },
  ],
  settings: [
    { tag: 'path', attrs: { d: 'M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.09a2 2 0 0 1-1-1.74v-.51a2 2 0 0 1 1-1.72l.15-.1a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z' } },
    { tag: 'circle', attrs: { cx: 12, cy: 12, r: 3 } },
  ],
  server: [
    { tag: 'rect', attrs: { width: 20, height: 8, x: 2, y: 2, rx: 2 } },
    { tag: 'rect', attrs: { width: 20, height: 8, x: 2, y: 14, rx: 2 } },
    { tag: 'path', attrs: { d: 'M6 6h.01' } },
    { tag: 'path', attrs: { d: 'M6 18h.01' } },
  ],
  'shield-check': [
    { tag: 'path', attrs: { d: 'M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.68 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.2 1.2 0 0 1 1.52 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1z' } },
    { tag: 'path', attrs: { d: 'm9 12 2 2 4-4' } },
  ],
  'table-2': [
    { tag: 'path', attrs: { d: 'M9 3H5a2 2 0 0 0-2 2v4h6z' } },
    { tag: 'path', attrs: { d: 'M21 9V5a2 2 0 0 0-2-2h-4v6z' } },
    { tag: 'path', attrs: { d: 'M3 15v4a2 2 0 0 0 2 2h4v-6z' } },
    { tag: 'path', attrs: { d: 'M15 21h4a2 2 0 0 0 2-2v-4h-6z' } },
    { tag: 'path', attrs: { d: 'M9 3v18' } },
    { tag: 'path', attrs: { d: 'M15 3v18' } },
    { tag: 'path', attrs: { d: 'M3 9h18' } },
    { tag: 'path', attrs: { d: 'M3 15h18' } },
  ],
  terminal: [
    { tag: 'path', attrs: { d: 'm4 17 6-6-6-6' } },
    { tag: 'path', attrs: { d: 'M12 19h8' } },
  ],
  'trash-2': [
    { tag: 'path', attrs: { d: 'M3 6h18' } },
    { tag: 'path', attrs: { d: 'M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2' } },
    { tag: 'path', attrs: { d: 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6' } },
    { tag: 'path', attrs: { d: 'M10 11v6' } },
    { tag: 'path', attrs: { d: 'M14 11v6' } },
  ],
  'user-round': [
    { tag: 'circle', attrs: { cx: 12, cy: 8, r: 5 } },
    { tag: 'path', attrs: { d: 'M20 21a8 8 0 0 0-16 0' } },
  ],
  wrench: [
    { tag: 'path', attrs: { d: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.1-3.1a6 6 0 0 1-7.9 7.9l-6.6 6.6a2.1 2.1 0 0 1-3-3l6.6-6.6a6 6 0 0 1 7.9-7.9z' } },
  ],
  x: [
    { tag: 'path', attrs: { d: 'M18 6 6 18' } },
    { tag: 'path', attrs: { d: 'm6 6 12 12' } },
  ],
  'x-circle': [
    { tag: 'circle', attrs: { cx: 12, cy: 12, r: 10 } },
    { tag: 'path', attrs: { d: 'm15 9-6 6' } },
    { tag: 'path', attrs: { d: 'm9 9 6 6' } },
  ],
}

const nodes = computed(() => icons[props.name] || icons.info)
</script>

<template>
  <svg
    class="icon"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <component
      :is="node.tag"
      v-for="(node, index) in nodes"
      :key="`${node.tag}-${index}`"
      v-bind="node.attrs"
    />
  </svg>
</template>
