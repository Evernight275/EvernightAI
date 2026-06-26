<script setup lang="ts">
import { computed } from 'vue'

type IconNode = {
  tag: 'path' | 'rect' | 'circle' | 'ellipse' | 'line' | 'polyline'
  attrs: Record<string, string | number>
}

const props = defineProps<{
  name: string
}>()

const icons: Record<string, IconNode[]> = {
  activity: [
    { tag: 'path', attrs: { d: 'M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2' } },
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
  database: [
    { tag: 'ellipse', attrs: { cx: 12, cy: 5, rx: 9, ry: 3 } },
    { tag: 'path', attrs: { d: 'M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5' } },
    { tag: 'path', attrs: { d: 'M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3' } },
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
  pencil: [
    { tag: 'path', attrs: { d: 'M21.17 6.83a2.83 2.83 0 0 0-4-4L3 17v4h4Z' } },
    { tag: 'path', attrs: { d: 'm15 5 4 4' } },
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
}

const nodes = computed(() => icons[props.name] || icons['message-square'])
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
