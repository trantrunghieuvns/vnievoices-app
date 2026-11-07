import sys
import json
import subprocess

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

queries = [
    "bản tin thời sự htv9 giọng đọc miền nam",
    "demo giọng đọc bản tin truyền hình miền nam nữ",
    "demo giọng đọc bản tin truyền hình miền bắc nữ",
]

for q in queries:
    print(f"=== QUERY: {q} ===")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json", "--flat-playlist",
        f"ytsearch6:{q}"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        print(f"  {d.get('id')} | {str(d.get('duration')):>5s}s | {d.get('title')}")
