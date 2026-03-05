/**
 * Shared overlay composable — single ContextMenu + SongDescriptionModal
 * instance at ArtistView level instead of one per SongRow/VersionRow.
 *
 * Eliminates hundreds of unnecessary component instances.
 */

import { ref, provide, inject, type InjectionKey } from 'vue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ContextMenuState {
  x: number
  y: number
  song?: any
  version?: any
  artistName?: string
  eraName?: string
  eraArt?: string
}

export interface DescriptionModalState {
  song?: any
  version?: any
  artistName?: string
  eraName?: string
  eraArt?: string
}

export interface SharedOverlays {
  // Context menu
  contextMenuState: ReturnType<typeof ref<ContextMenuState | null>>
  showContextMenu: (state: ContextMenuState) => void
  closeContextMenu: () => void

  // Description modal
  descriptionState: ReturnType<typeof ref<DescriptionModalState | null>>
  showDescription: (state: DescriptionModalState) => void
  closeDescription: () => void
}

// ---------------------------------------------------------------------------
// Injection key
// ---------------------------------------------------------------------------

export const SHARED_OVERLAYS_KEY: InjectionKey<SharedOverlays> = Symbol('shared-overlays')

// ---------------------------------------------------------------------------
// Provider (call in ArtistView)
// ---------------------------------------------------------------------------

export function provideSharedOverlays(): SharedOverlays {
  const contextMenuState = ref<ContextMenuState | null>(null)
  const descriptionState = ref<DescriptionModalState | null>(null)

  function showContextMenu(state: ContextMenuState) {
    contextMenuState.value = state
  }

  function closeContextMenu() {
    contextMenuState.value = null
  }

  function showDescription(state: DescriptionModalState) {
    descriptionState.value = state
  }

  function closeDescription() {
    descriptionState.value = null
  }

  const overlays: SharedOverlays = {
    contextMenuState,
    showContextMenu,
    closeContextMenu,
    descriptionState,
    showDescription,
    closeDescription,
  }

  provide(SHARED_OVERLAYS_KEY, overlays)
  return overlays
}

// ---------------------------------------------------------------------------
// Consumer (call in SongRow / VersionRow)
// ---------------------------------------------------------------------------

export function useSharedOverlays(): SharedOverlays {
  const overlays = inject(SHARED_OVERLAYS_KEY)
  if (!overlays) {
    throw new Error('useSharedOverlays() called without a provider. Wrap in ArtistView.')
  }
  return overlays
}
