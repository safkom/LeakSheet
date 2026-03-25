import { ref, onUnmounted } from 'vue'

const LONG_PRESS_MS = 500

/**
 * Returns touch event handlers that fire a callback after a long press.
 * Cancels if the user moves their finger (scroll) or lifts early.
 */
export function useLongPress(onLongPress: (x: number, y: number) => void) {
  let _timer: ReturnType<typeof setTimeout> | null = null
  let _onMove: ((e: TouchEvent) => void) | null = null
  const _fired = ref(false)

  function _removeMove() {
    if (_onMove) {
      document.removeEventListener('touchmove', _onMove)
      _onMove = null
    }
  }

  function onTouchStart(e: TouchEvent) {
    _fired.value = false
    const touch = e.touches[0]
    const startX = touch.clientX
    const startY = touch.clientY

    _timer = setTimeout(() => {
      _fired.value = true
      _removeMove()
      onLongPress(startX, startY)
      // Haptic feedback if available
      if (navigator.vibrate) navigator.vibrate(30)
    }, LONG_PRESS_MS)

    _onMove = (me: TouchEvent) => {
      const t = me.touches[0]
      if (Math.abs(t.clientX - startX) > 10 || Math.abs(t.clientY - startY) > 10) {
        cancel()
      }
    }
    document.addEventListener('touchmove', _onMove, { passive: true })
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
    _removeMove()
  }

  onUnmounted(cancel)

  return { onTouchStart, onTouchEnd }
}
