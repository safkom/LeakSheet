import { ref, onUnmounted } from 'vue'

const LONG_PRESS_MS = 500

/**
 * Returns touch event handlers that fire a callback after a long press.
 * Cancels if the user moves their finger (scroll) or lifts early.
 */
export function useLongPress(onLongPress: (x: number, y: number) => void) {
  let _timer: ReturnType<typeof setTimeout> | null = null
  const _fired = ref(false)

  function onTouchStart(e: TouchEvent) {
    _fired.value = false
    const touch = e.touches[0]
    const startX = touch.clientX
    const startY = touch.clientY

    _timer = setTimeout(() => {
      _fired.value = true
      onLongPress(startX, startY)
      // Haptic feedback if available
      if (navigator.vibrate) navigator.vibrate(30)
    }, LONG_PRESS_MS)

    // Cancel on move (scroll)
    const onMove = (me: TouchEvent) => {
      const t = me.touches[0]
      if (Math.abs(t.clientX - startX) > 10 || Math.abs(t.clientY - startY) > 10) {
        cancel()
        document.removeEventListener('touchmove', onMove)
      }
    }
    document.addEventListener('touchmove', onMove, { passive: true })
  }

  function onTouchEnd(e: Event) {
    if (_fired.value) {
      e.preventDefault()
    }
    cancel()
  }

  function cancel() {
    if (_timer) {
      clearTimeout(_timer)
      _timer = null
    }
  }

  onUnmounted(cancel)

  return { onTouchStart, onTouchEnd }
}
