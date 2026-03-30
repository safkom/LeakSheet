/**
 * Swipe action composable for song/version rows.
 *
 * Detects horizontal swipe gestures on touch devices.
 * - Swipe right: triggers onSwipeRight
 * - Swipe left: triggers onSwipeLeft
 *
 * Returns reactive offsetX for CSS transform binding.
 * Uses elastic rubber-band effect past the threshold.
 */
import { ref } from 'vue'

const TRIGGER_THRESHOLD = 60  // px to trigger the action
const RUBBER_BAND_FACTOR = 0.3 // resistance past threshold

export interface SwipeActionOptions {
  onSwipeRight?: () => void
  onSwipeLeft?: () => void
}

export function useSwipeAction(options: SwipeActionOptions) {
  const offsetX = ref(0)
  const isSwiping = ref(false)

  let _startX = 0
  let _startY = 0
  let _tracking = false
  let _axisLocked: 'horizontal' | 'vertical' | null = null

  function onTouchStart(e: TouchEvent): void {
    const t = e.touches[0]
    _startX = t.clientX
    _startY = t.clientY
    _tracking = true
    _axisLocked = null
    isSwiping.value = false
    offsetX.value = 0
  }

  function onTouchMove(e: TouchEvent): void {
    if (!_tracking) return
    const t = e.touches[0]
    const dx = t.clientX - _startX
    const dy = t.clientY - _startY

    // Lock axis after 10px movement
    if (_axisLocked === null) {
      if (Math.abs(dx) > 10 || Math.abs(dy) > 10) {
        _axisLocked = Math.abs(dx) > Math.abs(dy) ? 'horizontal' : 'vertical'
      }
    }

    if (_axisLocked !== 'horizontal') return

    isSwiping.value = true

    // Elastic rubber band past threshold
    const abs = Math.abs(dx)
    if (abs > TRIGGER_THRESHOLD) {
      const excess = abs - TRIGGER_THRESHOLD
      const elasticExcess = excess * RUBBER_BAND_FACTOR
      offsetX.value = Math.sign(dx) * (TRIGGER_THRESHOLD + elasticExcess)
    } else {
      offsetX.value = dx
    }
  }

  function onTouchEnd(_e: TouchEvent): void {
    if (!_tracking) return
    _tracking = false

    if (!isSwiping.value) {
      offsetX.value = 0
      return
    }

    const finalOffset = offsetX.value
    isSwiping.value = false
    offsetX.value = 0

    if (finalOffset >= TRIGGER_THRESHOLD && options.onSwipeRight) {
      navigator.vibrate?.(10)
      options.onSwipeRight()
    } else if (finalOffset <= -TRIGGER_THRESHOLD && options.onSwipeLeft) {
      navigator.vibrate?.(10)
      options.onSwipeLeft()
    }
  }

  function onTouchCancel(): void {
    _tracking = false
    isSwiping.value = false
    offsetX.value = 0
  }

  return {
    offsetX,
    isSwiping,
    onTouchStart,
    onTouchMove,
    onTouchEnd,
    onTouchCancel,
  }
}
