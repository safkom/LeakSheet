# LeakSheet

A REST API for parsing public Google Spreadsheets that contain leaked music data.

## Overview

LeakSheet fetches the HTML view of a public Google Spreadsheet and parses it into structured JSON. Spreadsheets are expected to follow the common "leak sheet" format where:

- Each **sheet tab** represents an artist.
- Within a sheet, **era header rows** (single merged cells spanning multiple columns) divide content into album eras / time periods.
- **Song rows** between era headers contain columns such as *Song Name*, *Version*, *Features*, *Notes*, and *Length*.

## Setup

```bash
pip install -r requirements.txt
```

## Running the API

```bash
uvicorn app.main:app --reload
```

Interactive docs are available at `http://localhost:8000/docs`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/parse?url=<url>` | Parse a spreadsheet from its full Google Sheets URL |
| GET | `/parse/{spreadsheet_id}` | Parse a spreadsheet by its ID |

### Example

```bash
curl "http://localhost:8000/parse/1hcRr6GIUNCV4z0iSXGxmLYrESkHfRxx6l5nk8d_Nsaw"
```

### Response shape

```json
{
  "spreadsheet_id": "1hcRr6...",
  "url": "https://docs.google.com/spreadsheets/d/1hcRr6.../htmlview",
  "sheets": [
    {
      "name": "Drake",
      "eras": [
        {
          "name": "Thank Me Later Era (2010)",
          "songs": [
            {
              "name": "Fear",
              "version": "Demo",
              "features": null,
              "notes": "Unreleased",
              "length": "3:42",
              "extra": {}
            }
          ]
        }
      ]
    }
  ]
}
```

## Running Tests

```bash
python -m pytest
```
