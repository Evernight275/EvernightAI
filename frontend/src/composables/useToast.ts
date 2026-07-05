export interface ToastOptions {
  duration?: number
}

class ToastService {
  private handler: {
    success: (message: string, duration?: number) => void
    error: (message: string, duration?: number) => void
    warning: (message: string, duration?: number) => void
    info: (message: string, duration?: number) => void
  } | null = null

  setHandler(handler: {
    success: (message: string, duration?: number) => void
    error: (message: string, duration?: number) => void
    warning: (message: string, duration?: number) => void
    info: (message: string, duration?: number) => void
  }) {
    this.handler = handler
  }

  success(message: string, options?: ToastOptions) {
    this.handler?.success(message, options?.duration)
  }

  error(message: string, options?: ToastOptions) {
    this.handler?.error(message, options?.duration)
  }

  warning(message: string, options?: ToastOptions) {
    this.handler?.warning(message, options?.duration)
  }

  info(message: string, options?: ToastOptions) {
    this.handler?.info(message, options?.duration)
  }
}

export const toast = new ToastService()

export function useToast() {
  return toast
}
