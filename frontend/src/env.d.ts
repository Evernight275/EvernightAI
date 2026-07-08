/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_EVERNIGHTAI_API_BASE?: string
}

interface Window {
  EVERNIGHTAI_API_BASE?: string
  EVERNIGHTAI_API_KEY?: string
}
