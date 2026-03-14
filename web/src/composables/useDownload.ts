import { onUnmounted } from 'vue'
import { toast } from 'vue-sonner'

export const MIME_TO_EXT: Record<string, string> = {
  'audio/mp4': '.m4a',
  'audio/mpeg': '.mp3',
  'audio/ogg': '.ogg',
  'audio/wav': '.wav',
  'audio/flac': '.flac',
  'audio/aac': '.aac',
  'audio/x-m4a': '.m4a',
}

/**
 * Composable for downloading audio files via the stream proxy.
 * Manages AbortController lifecycle and provides user-facing error toasts.
 */
export function useDownload() {
  let _controller: AbortController | null = null

  onUnmounted(() => {
    _controller?.abort()
  })

  async function download(link: string, filename: string): Promise<void> {
    const downloadUrl = `/api/stream?url=${encodeURIComponent(link)}&download=true`
    _controller?.abort()
    _controller = new AbortController()
    toast('Downloading...')
    try {
      const res = await fetch(downloadUrl, { signal: _controller.signal })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const ct = res.headers.get('content-type')?.split(';')[0].trim() || ''
      const ext = MIME_TO_EXT[ct] || '.mp3'
      const blob = await res.blob()
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      a.download = `${filename}${ext}`
      a.click()
      URL.revokeObjectURL(objUrl)
      toast.success('Download complete')
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') return
      if (e instanceof Error && e.name === 'TimeoutError') {
        toast.error('Download timed out — check your connection')
      } else {
        toast.error('Download failed — try right-clicking for other versions')
      }
    }
  }

  return { download }
}
