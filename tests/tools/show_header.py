"""Show header row columns for Kendrick tracker."""
from src.parser import extract_table
rows = extract_table(open('Trackers/Kendrick Lamar Music Tracker - Google Drive_files/sheet.html').read())
header = rows[0]
for i, cell in enumerate(header):
    t = cell.text.strip()
    print(f"  col {i}: {t!r}")
