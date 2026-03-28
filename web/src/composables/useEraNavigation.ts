/**
 * Era navigation composable.
 *
 * Tracks which era is in the viewport and exposes scroll-to-era / scroll-to-top.
 * Used by EraNav (side rail) and ScrollToTop button.
 */
import { ref } from 'vue'

export function useEraNavigation() {
  const activeEraName = ref<string | null>(null)
  const showScrollTop = ref(false)

  let _observer: IntersectionObserver | null = null
  let _eraOrder: string[] = []

  /**
   * Set up IntersectionObserver on all era block elements.
   * Call after the era list is rendered; call cleanup() on unmount.
   */
  function setupObservers(eraElements: Record<string, HTMLElement | null>): void {
    _observer?.disconnect()

    _eraOrder = Object.keys(eraElements).filter(k => eraElements[k] !== null)
    if (!_eraOrder.length) return

    // Track how far down the page we are for scroll-to-top visibility
    // (show after the 3rd era has been scrolled past)
    const thirdEraName = _eraOrder[2] ?? _eraOrder[_eraOrder.length - 1]
    const thirdEraEl = eraElements[thirdEraName]

    const visibleEras = new Set<string>()

    _observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const name = (entry.target as HTMLElement).dataset.eraName
          if (!name) continue
          if (entry.isIntersecting) {
            visibleEras.add(name)
          } else {
            visibleEras.delete(name)
          }
        }

        // Active era = first visible one in document order
        for (const name of _eraOrder) {
          if (visibleEras.has(name)) {
            activeEraName.value = name
            break
          }
        }

        // Show scroll-to-top once the 3rd era has left the viewport at the top
        if (thirdEraEl) {
          const rect = thirdEraEl.getBoundingClientRect()
          showScrollTop.value = rect.bottom < 0
        }
      },
      {
        rootMargin: '-10% 0px -60% 0px',
        threshold: 0,
      }
    )

    for (const name of _eraOrder) {
      const el = eraElements[name]
      if (el) {
        el.dataset.eraName = name
        _observer.observe(el)
      }
    }

    // Also track scroll position for showScrollTop independently
    _setupScrollListener(thirdEraEl)
  }

  let _scrollHandler: (() => void) | null = null

  function _setupScrollListener(thirdEraEl: HTMLElement | null | undefined): void {
    if (_scrollHandler) {
      window.removeEventListener('scroll', _scrollHandler)
    }
    if (!thirdEraEl) return
    let _rafPending = false
    _scrollHandler = () => {
      if (_rafPending) return
      _rafPending = true
      requestAnimationFrame(() => {
        _rafPending = false
        showScrollTop.value = thirdEraEl.getBoundingClientRect().bottom < 0
      })
    }
    window.addEventListener('scroll', _scrollHandler, { passive: true })
  }

  function scrollToEra(eraName: string, eraElements: Record<string, HTMLElement | null>): void {
    const el = eraElements[eraName]
    if (!el) return
    const y = el.getBoundingClientRect().top + window.scrollY - 8
    window.scrollTo({ top: y, behavior: 'smooth' })
  }

  function scrollToTop(): void {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function cleanup(): void {
    _observer?.disconnect()
    _observer = null
    if (_scrollHandler) {
      window.removeEventListener('scroll', _scrollHandler)
      _scrollHandler = null
    }
  }

  return {
    activeEraName,
    showScrollTop,
    setupObservers,
    scrollToEra,
    scrollToTop,
    cleanup,
  }
}
