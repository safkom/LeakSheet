"""Check Kendrick tracker for date fields to diagnose recents issue."""
import json, subprocess, sys

url = sys.argv[1] if len(sys.argv) > 1 else "https://docs.google.com/spreadsheets/d/1ogXipStHPpqEMgCDvxpWXQ7Yzly3YZx6riP25ChoxNM/htmlview"

result = subprocess.run(
    ['curl', '-s', 'http://localhost:8000/api/sheet',
     '-H', 'Content-Type: application/json',
     '-d', json.dumps({"url": url})],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
print(f"Artist: {data['name']}, Eras: {len(data['eras'])}")

count_with_dates = 0
count_total = 0
for era in data['eras']:
    for sec in era.get('sections', []):
        for song in sec.get('songs', []):
            for v in song.get('versions', []):
                count_total += 1
                ld = v.get('leak_date')
                fd = v.get('file_date')
                if ld or fd:
                    count_with_dates += 1

print(f"Total versions: {count_total}, With dates: {count_with_dates}")

# Show first 10 with dates
shown = 0
for era in data['eras']:
    for sec in era.get('sections', []):
        for song in sec.get('songs', []):
            for v in song.get('versions', []):
                ld = v.get('leak_date')
                fd = v.get('file_date')
                if (ld or fd) and shown < 10:
                    print(f"  {v['name']}: leak_date={ld!r}, file_date={fd!r}")
                    shown += 1

# Show first 3 without dates
if count_total > count_with_dates:
    print(f"\nVersions WITHOUT dates ({count_total - count_with_dates}):")
    shown = 0
    for era in data['eras']:
        for sec in era.get('sections', []):
            for song in sec.get('songs', []):
                for v in song.get('versions', []):
                    ld = v.get('leak_date')
                    fd = v.get('file_date')
                    if not ld and not fd and shown < 3:
                        print(f"  {v['name']}: avail={v.get('available_length')!r}")
                        shown += 1
