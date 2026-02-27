# LeakSheet Web UI

Vue 3 frontend for LeakSheet. Provides a music tracker browser with search, collapsible era cards, audio streaming, and detailed song metadata.

## Setup

```bash
npm install
npm run dev      # Dev server (proxies /api to backend)
npm run build    # Production build
```

The dev server proxies `/api` requests to `http://localhost:8000` (the FastAPI backend). Start both servers for local development.

## Features

- Tracker URL input with validation and multi-tracker history
- Artist view with real-time search/filter across eras and songs
- Era cards with cover art color extraction (ColorThief)
- Audio streaming via backend proxy (pillows.su, imgur.gg)
- Player bar with seek, volume, buffering indicators
- Right-click context menu (copy link, download)
- Song description modal with credits, samples, links
- Keyboard shortcuts: Space (play/pause), Arrow Left/Right (seek), Arrow Up/Down (volume)
