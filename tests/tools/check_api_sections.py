"""Check API response for Ye tracker sections."""
import json, subprocess, sys

result = subprocess.run(
    ['curl', '-s', 'http://localhost:8000/api/sheet',
     '-H', 'Content-Type: application/json',
     '-d', '{"url":"https://yetracker.net/","force_refresh":true}'],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
print(f"Artist: {data['name']}, Eras: {len(data['eras'])}")
for era in data['eras']:
    sections = era.get('sections', [])
    if len(sections) > 1:
        named = [s['name'] for s in sections if s.get('name')]
        if named:
            counts = [(s.get('name','(default)'), len(s.get('songs',[]))) for s in sections]
            print(f"  {era['name']}: {counts}")
