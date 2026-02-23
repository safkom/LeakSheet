# LeakSheet

Parser + API for Google Spreadsheet-based music tracker documents. These spreadsheets catalog unreleased/leaked music from artists, organized into album/mixtape "eras."

## Quick Start

```bash
pip install -r requirements.txt

# Parse local HTML exports
python -c "from src.parser import parse_tracker_directory; artists = parse_tracker_directory('Trackers'); print(f'{len(artists)} artists parsed')"

# Parse a live Google Sheets URL
python -c "from src.fetcher import fetch_and_parse; a = fetch_and_parse('https://yetracker.net/'); print(f'{a.name}: {a.total_songs} songs')"

# Inspect with CLI tools
python -m tests.tools.inspect_eras --tracker ye
python -m tests.tools.inspect_songs --tracker ye --era "Yeezus 2"
python -m tests.tools.dump_raw_table --tracker ye --start 0 --rows 5

# Run tests
python -m pytest tests/
```

## Input Sources

| Source | Example |
|--------|---------|
| Local HTML export | `Trackers/Ye Tracker - Google Drive_files/sheet.html` |
| Google Sheets htmlview | `docs.google.com/spreadsheets/d/{id}/htmlview` |
| Custom tracker domain | `yetracker.net` (redirects to htmlview) |
| Links file | `Trackers/links.txt` (one URL per line) |

## Data Hierarchy

```
Artist
  └── Era (album/mixtape period)
        └── Song (logical song, may have multiple versions)
              └── SongVersion (specific leak/recording with metadata)
```

## Supported Trackers

| Artist | Local | Live URL |
|--------|-------|----------|
| Ye | ✅ | `yetracker.net` |
| Kendrick Lamar | ✅ | Google Sheets htmlview |
| Baby Keem | ✅ | Google Sheets htmlview |
| Playboi Carti | ✅ | Google Sheets htmlview |

## CLI Tools

| Tool | Purpose |
|------|---------|
| `tests/tools/dump_raw_table.py` | Dump raw HTML table rows |
| `tests/tools/inspect_eras.py` | Show eras with song/version counts |
| `tests/tools/inspect_songs.py` | Inspect parsed songs with filters |
| `tests/tools/diff_trackers.py` | Compare column layouts across trackers |
| `tests/tools/debug_zero_eras.py` | Diagnose eras with 0 matched songs |

## Architecture

See [agents.md](agents.md) for detailed architecture, data model, parsing strategy, and API design.