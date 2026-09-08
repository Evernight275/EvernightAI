import { onBeforeUnmount, shallowRef, watch, type ComponentPublicInstance } from 'vue'

export function useDialog(
  isOpen: () => boolean,
  close: () => void,
  isModal: () => boolean = () => true,
) {
  const dialog = shallowRef<HTMLDialogElement | null>(null)

  watch([dialog, isOpen, isModal], ([element, open, modal]) => {
    if (!element) return
    if (element.open && (!open || element.matches(':modal') !== modal)) {
      element.close()
    }
    if (open && !element.open) {
      if (modal) element.showModal()
      else element.show()
    }
  }, { flush: 'post' })

  onBeforeUnmount(() => dialog.value?.close())

  function onCancel(event: Event): void {
    event.preventDefault()
    close()
  }

  function onBackdropClick(event: MouseEvent): void {
    const element = dialog.value
    if (!element || event.target !== element || !isModal()) return
    const rect = element.getBoundingClientRect()
    if (event.clientX < rect.left || event.clientX > rect.right
      || event.clientY < rect.top || event.clientY > rect.bottom) close()
  }

  function onKeydown(event: KeyboardEvent): void {
    const element = dialog.value
    if (event.key !== 'Tab' || !element || !isModal()) return
    const focusable = [...element.querySelectorAll<HTMLElement>(
      'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]',
    )].filter((item) => item.getClientRects().length > 0)
    const first = focusable[0]
    const last = focusable.at(-1)
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first?.focus()
    }
  }

  function setDialog(element: Element | ComponentPublicInstance | null): void {
    dialog.value = element as HTMLDialogElement | null
  }

  return { setDialog, onCancel, onBackdropClick, onKeydown }
}
