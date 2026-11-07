import sys
import os
import json
import time
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import imageio_ffmpeg
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
REF_DIR = Path(r"d:\GS\ANTI\APP\vbee_studio\voices_ref")
REF_DIR.mkdir(parents=True, exist_ok=True)

MC_QUERIES = [
    {
        "id": "mc_quyen_linh",
        "name": "MC Quyền Linh",
        "query": "ytsearch3:MC Quyền Linh tâm sự cuộc sống phỏng vấn không nhạc",
        "ss": "25",
        "dur": "6.8",
        "gender": "Nam",
        "description": "Nam · Miền Nam · Trầm ấm, mộc mạc, truyền cảm như MC Quyền Linh",
    },
    {
        "id": "mc_thanh_bach",
        "name": "MC Thanh Bạch",
        "query": "ytsearch3:MC Thanh Bạch chia sẻ phỏng vấn giọng nói",
        "ss": "20",
        "dur": "6.5",
        "gender": "Nam",
        "description": "Nam · Sân Khấu · Sôi động, giàu năng lượng, nhấn nhá như MC Thanh Bạch",
    },
    {
        "id": "mc_nguyen_ngoc_ngan",
        "name": "MC Nguyễn Ngọc Ngạn",
        "query": "ytsearch3:Nguyễn Ngọc Ngạn đọc truyện đêm khuya",
        "ss": "35",
        "dur": "7.0",
        "gender": "Nam",
        "description": "Nam · Kể Chuyện · Trầm mặc, sâu lắng, huyền thoại đọc truyện đêm khuya",
    },
    {
        "id": "mc_lai_van_sam",
        "name": "MC Lại Văn Sâm",
        "query": "ytsearch3:MC Lại Văn Sâm chia sẻ phỏng vấn",
        "ss": "25",
        "dur": "6.5",
        "gender": "Nam",
        "description": "Nam · Miền Bắc · Điềm đạm, hóm hỉnh, truyền cảm hứng kinh điển",
    },
    {
        "id": "mc_tran_thanh",
        "name": "MC Trấn Thành",
        "query": "ytsearch3:Trấn Thành tâm sự podcast không nhạc",
        "ss": "25",
        "dur": "6.5",
        "gender": "Nam",
        "description": "Nam · Mạng Xã Hội · Tự sự đời thường, nghẹn ngào, chạm cảm xúc",
    },
]

def download_mc_clip(item):
    out_wav = REF_DIR / f"{item['id']}.wav"
    out_mp3 = REF_DIR / f"{item['id']}_sample.mp3"
    if out_wav.exists() and out_wav.stat().st_size > 50000:
        print(f"[SKIP] {item['name']} already exists ({out_wav.stat().st_size} bytes)")
        return out_wav
    tmp_audio = REF_DIR / f"{item['id']}_raw.m4a"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "--match-filter", "duration > 45 & duration < 1800",
        "--no-playlist",
        "--max-downloads", "1",
        "-o", str(tmp_audio),
        item["query"]
    ]
    print(f"Downloading reference for {item['name']}...")
    subprocess.run(cmd, capture_output=True, text=True)
    # Find downloaded file
    candidates = list(REF_DIR.glob(f"{item['id']}_raw*"))
    if not candidates:
        print(f"Warning: Could not download {item['name']}")
        return None
    raw_file = candidates[0]
    subprocess.run([
        FFMPEG, "-y", "-ss", item["ss"], "-t", item["dur"],
        "-i", str(raw_file),
        "-af", "highpass=f=85,lowpass=f=12000,dynaudnorm",
        "-ar", "48000", "-ac", "1",
        str(out_wav)
    ], check=True, capture_output=True)
    subprocess.run([
        FFMPEG, "-y", "-ss", item["ss"], "-t", "10",
        "-i", str(raw_file),
        "-c:a", "libmp3lame", "-b:a", "160k",
        str(out_mp3)
    ], check=True, capture_output=True)
    try:
        raw_file.unlink()
    except Exception:
        pass
    print(f"Saved {out_wav.name} ({out_wav.stat().st_size} bytes)")
    return out_wav

for item in MC_QUERIES:
    try:
        download_mc_clip(item)
    except Exception as e:
        print(f"Error on {item['name']}: {e}")
