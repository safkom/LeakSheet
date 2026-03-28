/**
 * Shared overlay composable — single ContextMenu + SongDescriptionModal
 * instance at ArtistView level instead of one per SongRow/VersionRow.
 *
 * Eliminates hundreds of unnecessary component instances.
 */

import { ref, provide, inject, nextTick, type InjectionKey } from 'vue'
import type { Song, SongVersion } from './useEraFiltering'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ContextMenuState {
  x: number
  y: number
  song?: Song
  version?: SongVersion
  artistName?: string
  artistSlug?: string
  sourceUrl?: string | null
  eraName?: string
  eraArt?: string
}

export interface DescriptionModalState {
  song?: Song
  version?: SongVersion
  artistName?: string
  artistSlug?: string
  sourceUrl?: string | null
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

  async function showContextMenu(state: ContextMenuState) {
    // Close old menu first so its document listeners are removed
    // before the new menu mounts and registers its own listeners.
    contextMenuState.value = null
    await nextTick()
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
