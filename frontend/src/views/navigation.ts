export const viewKeys = [
  'workbench',
  'chat',
  'tools',
  'runs',
  'analytics',
  'agents',
  'memories',
  'logs',
] as const

export type ViewKey = (typeof viewKeys)[number]
