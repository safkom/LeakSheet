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

// Regex patterns for supported hosts
const _PILLOWS_RE = /^https?:\/\/(?:www\.)?(pillows\.su|pillowcase\.su)\/f\/([A-Za-z0-9_-]+)/i
const _IMGUR_RE = /^https?:\/\/(?:www\.)?((?:temp\.)?imgur\.gg)\/f\/([A-Za-z0-9_-]+)/i
const _FROSTE_RE = /^https?:\/\/music\.froste\.lol\/song\/([a-f0-9]+)/i

/**
 * Resolve original file-sharing link to its native download URL.
 *
 * - pillows.su / pillowcase.su → https://api.pillows.su/api/download/{id}
 * - music.froste.lol → https://music.froste.lol/song/{id}/download
 * - imgur.gg — uses direct CDN link (the original link itself serves the file)
 * - krakenfiles — no separate download endpoint, falls back to stream proxy
 */
function resolveDownloadUrl(link: string): string {
  let m = _PILLOWS_RE.exec(link)
  if (m) {
    const id = m[2]
    return `https://api.pillows.su/api/download/${id}`
  }

  m = _FROSTE_RE.exec(link)
  if (m) {
    const id = m[1]
    return `https://music.froste.lol/song/${id}/download`
  }

  // imgur.gg: the link itself is CDN-served; use it directly
  m = _IMGUR_RE.exec(link)
  if (m) {
    return link
  }

  // Fallback: use stream proxy
  return link
}

/**
 * Core download logic — uses the correct download endpoint per host,
 * proxied through the backend for CORS.
 * Standalone function (not a composable) so it can be called from
 * contexts that don't have a Vue lifecycle (e.g. module-level controllers).
 */
export async function downloadFile(
  link: string,
  filename: string,
  signal?: AbortSignal,
): Promise<void> {
  const actualDownloadUrl = resolveDownloadUrl(link)
  const downloadUrl = `/api/stream?url=${encodeURIComponent(actualDownloadUrl)}&download=true`

  const toastId = toast.loading(`Downloading ${filename}...`)
  try {
    const res = await fetch(downloadUrl, { signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const ct = res.headers.get('content-type')?.split(';')[0].trim() || ''
    const ext = MIME_TO_EXT[ct] || '.mp3'

    // Stream with progress if Content-Length is available
    const total = parseInt(res.headers.get('content-length') || '0', 10)
    let blob: Blob

    if (total > 0 && res.body) {
      const reader = res.body.getReader()
      const chunks: Uint8Array[] = []
      let received = 0

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        chunks.push(value)
        received += value.length
        const pct = Math.round((received / total) * 100)
        toast.loading(`Downloading ${filename}... ${pct}%`, { id: toastId })
      }

      blob = new Blob(chunks, { type: ct || 'application/octet-stream' })
    } else {
      blob = await res.blob()
    }

    const objUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objUrl
    a.download = `${filename}${ext}`
    a.click()
    URL.revokeObjectURL(objUrl)
    toast.success('Download complete', { id: toastId })
  } catch (e: unknown) {
    if (e instanceof Error && e.name === 'AbortError') {
      toast.dismiss(toastId)
      return
    }
    if (e instanceof Error && e.name === 'TimeoutError') {
      toast.error('Download timed out — check your connection', { id: toastId })
    } else {
      toast.error('Download failed — try right-clicking for other versions', { id: toastId })
    }
  }
}

/**
 * Composable for downloading audio files via the stream proxy.
 * Manages AbortController lifecycle tied to the component's onUnmounted.
 */
export function useDownload() {
  let _controller: AbortController | null = null

  onUnmounted(() => {
    _controller?.abort()
  })

  async function download(link: string, filename: string): Promise<void> {
    _controller?.abort()
    _controller = new AbortController()
    await downloadFile(link, filename, _controller.signal)
  }

  return { download }
}
