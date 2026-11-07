import sys
import os
import time
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
import imageio_ffmpeg
from vieneu import Vieneu

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
REF_DIR = Path(r"d:\GS\ANTI\APP\vbee_studio\voices_ref")
PREV_DIR = Path(r"d:\GS\ANTI\APP\vbee_studio\netlify_site\previews")
REF_DIR.mkdir(parents=True, exist_ok=True)
PREV_DIR.mkdir(parents=True, exist_ok=True)

FEMALE_MCS_KOLS = [
    {
        "id": "mc_khanh_vy",
        "name": "MC Khánh Vy (GenZ Năng Lượng VTV)",
        "query": "ytsearch3:Khánh Vy chia sẻ tiếng Anh vlog tâm sự",
        "description": "Nữ · Bắc · Trẻ trung, thông minh, năng lượng tích cực chuẩn MC VTV",
        "sample": "Xin chào mọi người, hôm nay mình muốn chia sẻ một bí quyết nhỏ giúp bạn luôn giữ được nguồn năng lượng tích cực mỗi ngày.",
    },
    {
        "id": "btv_hoai_anh",
        "name": "BTV Hoài Anh (Thời Sự Miền Nam Ngọt Ngào)",
        "query": "ytsearch3:BTV Hoài Anh chia sẻ phỏng vấn giọng nói",
        "description": "Nữ · Nam · Ngọt ngào, truyền cảm, chuẩn mực bản tin VTV",
        "sample": "Cảm ơn quý vị đã luôn đồng hành và dành những tình cảm thật ấm áp cho chương trình trong suốt thời gian qua.",
    },
    {
        "id": "mc_lieu_ha_trinh",
        "name": "MC Liêu Hà Trinh (Tự Sự Chữa Lành)",
        "query": "ytsearch3:Liêu Hà Trinh tâm sự podcast tình yêu",
        "description": "Nữ · Nam · Sâu lắng, thơ mộng, kể chuyện tình yêu & chữa lành",
        "sample": "Đôi khi chúng ta cần học cách ôm lấy những tổn thương của chính mình, để nhận ra bản thân đã mạnh mẽ nhường nào.",
    },
    {
        "id": "mc_mai_ngoc",
        "name": "MC Mai Ngọc (Thanh Lịch VTV)",
        "query": "ytsearch3:MC Mai Ngọc chia sẻ cuộc sống phỏng vấn",
        "description": "Nữ · Bắc · Dịu dàng, sang trọng, phát âm tròn vành rõ chữ",
        "sample": "Một buổi sáng dịu dàng bắt đầu bằng tách trà ấm và những dự định mới đầy hứng khởi đang chờ đón phía trước.",
    },
    {
        "id": "mc_thao_van",
        "name": "MC Thảo Vân (Ấm Áp Tình Cảm)",
        "query": "ytsearch3:MC Thảo Vân chia sẻ tâm sự cuộc sống",
        "description": "Nữ · Bắc · Hiền hậu, truyền cảm, đằm thắm đi vào lòng người",
        "sample": "Gia đình luôn là bến đỗ bình yên nhất, nơi mà dù đi đâu về đâu, ta vẫn luôn tìm thấy sự chở che dịu dàng.",
    },
    {
        "id": "koc_vo_ha_linh",
        "name": "KOC Võ Hà Linh (Chiến Thần Review)",
        "query": "ytsearch3:Võ Hà Linh review mỹ phẩm tâm sự",
        "description": "Nữ · KOC · Dứt khoát, cuốn hút, nhấn nhá chốt đơn triệu view",
        "sample": "Mọi người ơi, em này thực sự là chân ái luôn nhé, chất cực kỳ mịn mà giá lại siêu hời, chốt đơn ngay kẻo lỡ!",
    },
    {
        "id": "kol_hannah_olala",
        "name": "KOL Hannah Olala (Luxury & Lifestyle)",
        "query": "ytsearch3:Hannah Olala chia sẻ làm đẹp cuộc sống",
        "description": "Nữ · Nam · Sang trọng, nhẹ nhàng, truyền cảm hứng phụ nữ hiện đại",
        "sample": "Phụ nữ đẹp nhất là khi tự tin làm chủ cuộc sống của mình và biết yêu thương, chăm sóc bản thân mỗi ngày.",
    },
    {
        "id": "kol_giang_oi",
        "name": "KOL Giang Ơi (Storytelling Đời Thường)",
        "query": "ytsearch3:Giang Ơi tâm sự người lớn",
        "description": "Nữ · Bắc · Tự nhiên, thông thái, kể chuyện vlog cuốn hút",
        "sample": "Chào các bạn, hôm nay chúng mình hãy cùng ngồi xuống trò chuyện về những bài học trưởng thành mà ai cũng từng đi qua nhé.",
    },
    {
        "id": "mc_thuy_minh",
        "name": "MC Thùy Minh (Have A Sip Podcast)",
        "query": "ytsearch3:Thùy Minh Have A Sip chia sẻ",
        "description": "Nữ · Bắc · Trầm ấm, sắc sảo, chất giọng podcast đặc trưng",
        "sample": "Chào mừng bạn đến với buổi trò chuyện hôm nay, hãy rót cho mình một tách cà phê ấm và cùng lắng nghe câu chuyện này.",
    },
    {
        "id": "mc_ky_duyen",
        "name": "MC Nguyễn Cao Kỳ Duyên (Quý Phái Sân Khấu)",
        "query": "ytsearch3:MC Kỳ Duyên chia sẻ tâm sự cuộc sống",
        "description": "Nữ · Hải Ngoại · Duyên dáng, sang trọng, kể chuyện đầy cuốn hút",
        "sample": "Thưa quý vị, mỗi bài hát, mỗi câu chuyện đều mang theo một kỷ niệm đẹp mà thời gian không bao giờ xóa nhòa được.",
    },
]

def find_best_female_window(wav_path: Path, dur_sec: float = 6.8) -> float:
    data, sr = sf.read(str(wav_path))
    if data.ndim > 1:
        data = data.mean(axis=1)
    best_st = 15.0
    best_score = -1.0
    max_st = min(int(len(data) / sr) - int(dur_sec) - 2, 140)
    for st in range(8, max(12, max_st), 4):
        seg = data[int(st * sr):int((st + dur_sec) * sr)]
        if len(seg) < int(6.0 * sr):
            continue
        rms = float(np.sqrt(np.mean(seg ** 2)))
        if rms < 0.03:
            continue
        pitches = []
        flen = int(0.04 * sr)
        hop = int(0.015 * sr)
        for i in range(0, len(seg) - flen, hop):
            fr = seg[i:i + flen]
            if np.sqrt(np.mean(fr ** 2)) < 0.025:
                continue
            corr = np.correlate(fr, fr, mode="full")[flen - 1:]
            lmin, lmax = int(sr / 380), int(sr / 110)
            lag = int(np.argmax(corr[lmin:lmax])) + lmin
            if corr[lag] > 0.42 * corr[0]:
                pitches.append(sr / lag)
        if len(pitches) >= 60:
            med_f0 = float(np.median(pitches))
            if 168.0 <= med_f0 <= 310.0:
                score = len(pitches) * min(rms, 0.18)
                if score > best_score:
                    best_score = score
                    best_st = float(st)
                    if len(pitches) >= 130 and rms >= 0.055:
                        break
    return best_st

for item in FEMALE_MCS_KOLS:
    out_wav = REF_DIR / f"{item['id']}.wav"
    if out_wav.exists() and out_wav.stat().st_size > 100000:
        print(f"[SKIP] {item['name']} already downloaded.")
        continue
    tmp_raw = REF_DIR / f"{item['id']}_raw.m4a"
    print(f"Downloading {item['name']}...")
    subprocess.run([
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "--no-playlist", "--max-downloads", "1",
        "-o", str(tmp_raw),
        item["query"]
    ], capture_output=True, text=True)
    cands = list(REF_DIR.glob(f"{item['id']}_raw*"))
    if not cands:
        print(f"Warning: could not download {item['name']}")
        continue
    raw_file = cands[0]
    probe_wav = REF_DIR / f"{item['id']}_probe.wav"
    subprocess.run([
        FFMPEG, "-y", "-i", str(raw_file), "-t", "150", "-ar", "24000", "-ac", "1", str(probe_wav)
    ], capture_output=True)
    st_sec = 20.0
    if probe_wav.exists():
        try:
            st_sec = find_best_female_window(probe_wav, 6.8)
        except Exception:
            st_sec = 20.0
        probe_wav.unlink(missing_ok=True)
    subprocess.run([
        FFMPEG, "-y", "-ss", str(st_sec), "-t", "6.8",
        "-i", str(raw_file),
        "-af", "highpass=f=95,lowpass=f=12500,dynaudnorm",
        "-ar", "48000", "-ac", "1", str(out_wav)
    ], check=True, capture_output=True)
    raw_file.unlink(missing_ok=True)
    print(f" -> Extracted clean 48kHz ref at t={st_sec}s: {out_wav.name} ({out_wav.stat().st_size} bytes)")

print("Loading VieNeu-TTS v3 Turbo to enroll 10 Female MCs/KOLs/KOCs...")
tts = Vieneu(mode="v3turbo", precision="fp32")

for idx, item in enumerate(FEMALE_MCS_KOLS, start=7):
    wpath = REF_DIR / f"{item['id']}.wav"
    if not wpath.exists():
        continue
    t0 = time.time()
    tts.add_voice(
        name=item["name"],
        ref_audio=str(wpath),
        denoise=True,
        use_ref_codes=True,
        description=item["description"],
        gender="female",
        save=False,
    )
    if item["name"] in tts._preset_voices:
        tts._preset_voices[item["name"]]["featured"] = idx
    print(f"Enrolled '{item['name']}' in {time.time() - t0:.2f}s")

    # Generate preview MP3
    out_mp3 = PREV_DIR / f"{item['id']}.mp3"
    if not out_mp3.exists() or out_mp3.stat().st_size < 10000:
        wav = tts.infer(item["sample"], voice=item["name"], temperature=0.78, apply_watermark=False)
        tmp_w = PREV_DIR / f"{item['id']}.wav"
        sf.write(str(tmp_w), wav, tts.sample_rate)
        subprocess.run([
            FFMPEG, "-y", "-i", str(tmp_w),
            "-af", "dynaudnorm=f=150:g=15",
            "-c:a", "libmp3lame", "-b:a", "192k", str(out_mp3)
        ], check=True, capture_output=True)
        tmp_w.unlink(missing_ok=True)
        print(f" -> Generated preview {out_mp3.name} ({out_mp3.stat().st_size} bytes)")

saved = tts.save_voices()
(REF_DIR / "voices_v3_turbo_enrolled.json").write_text(Path(saved).read_text(encoding="utf-8"), encoding="utf-8")
print("ALL 16 CELEBRITY / VBEE / KOL / KOC VOICES ENROLLED & SAVED!")
