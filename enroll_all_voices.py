import sys
import os
import time
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import imageio_ffmpeg
import soundfile as sf
from vieneu import Vieneu

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
REF_DIR = Path(r"d:\GS\ANTI\APP\vbee_studio\voices_ref")

# Ensure MC Nguyen Ngoc Ngan clip is downloaded
nnn_wav = REF_DIR / "mc_nguyen_ngoc_ngan.wav"
nnn_mp3 = REF_DIR / "mc_nguyen_ngoc_ngan_sample.mp3"
if not nnn_wav.exists() or nnn_wav.stat().st_size < 50000:
    print("Downloading MC Nguyễn Ngọc Ngạn reference clip...")
    tmp_nnn = REF_DIR / "nnn_raw.m4a"
    subprocess.run([
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "--no-playlist",
        "--max-downloads", "1",
        "-o", str(tmp_nnn),
        "ytsearch3:MC Nguyễn Ngọc Ngạn tâm sự chia sẻ"
    ], capture_output=True, text=True)
    cands = list(REF_DIR.glob("nnn_raw*"))
    if cands:
        subprocess.run([
            FFMPEG, "-y", "-ss", "25", "-t", "6.8",
            "-i", str(cands[0]),
            "-af", "highpass=f=85,lowpass=f=12000,dynaudnorm",
            "-ar", "48000", "-ac", "1",
            str(nnn_wav)
        ], check=True, capture_output=True)
        subprocess.run([
            FFMPEG, "-y", "-ss", "25", "-t", "10",
            "-i", str(cands[0]),
            "-c:a", "libmp3lame", "-b:a", "160k",
            str(nnn_mp3)
        ], check=True, capture_output=True)
        try:
            cands[0].unlink()
        except Exception:
            pass
        print("Saved mc_nguyen_ngoc_ngan.wav:", nnn_wav.stat().st_size)

print("Initializing VieNeu-TTS v3 Turbo (48kHz ONNX Engine)...")
t0 = time.time()
tts = Vieneu(mode="v3turbo", precision="fp32")
print(f"VieNeu-TTS v3 Turbo loaded in {time.time() - t0:.2f}s!")

CUSTOM_VOICES = [
    {
        "name": "Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)",
        "wav": REF_DIR / "vbee_uploaded_exact_ref.wav",
        "gender": "female",
        "description": "Nữ · Miền Bắc · Giọng đọc truyện ngôn tình truyền cảm chuẩn Vbee (Mẫu gốc đính kèm)",
        "denoise": False,
    },
    {
        "name": "MC Quyền Linh (Truyền Cảm Đời Thường)",
        "wav": REF_DIR / "mc_quyen_linh.wav",
        "gender": "male",
        "description": "Nam · Miền Nam · Trầm ấm, mộc mạc, nhân văn như MC Quyền Linh",
        "denoise": True,
    },
    {
        "name": "MC Thanh Bạch (Sôi Động Sân Khấu)",
        "wav": REF_DIR / "mc_thanh_bach.wav",
        "gender": "male",
        "description": "Nam · Sân Khấu · Hào hứng, nhấn nhá truyền lửa như MC Thanh Bạch",
        "denoise": True,
    },
    {
        "name": "MC Nguyễn Ngọc Ngạn (Kể Chuyện Đêm Khuya)",
        "wav": REF_DIR / "mc_nguyen_ngoc_ngan.wav",
        "gender": "male",
        "description": "Nam · Kể Chuyện · Trầm mặc, sâu lắng, huyền thoại đọc truyện",
        "denoise": True,
    },
    {
        "name": "MC Lại Văn Sâm (Điềm Đạm Kinh Điển)",
        "wav": REF_DIR / "mc_lai_van_sam.wav",
        "gender": "male",
        "description": "Nam · Miền Bắc · Điềm đạm, thông thái, truyền cảm hứng kinh điển",
        "denoise": True,
    },
    {
        "name": "MC Trấn Thành (Tự Sự Chạm Cảm Xúc)",
        "wav": REF_DIR / "mc_tran_thanh.wav",
        "gender": "male",
        "description": "Nam · Mạng Xã Hội · Tự sự đời thường, nghẹn ngào, cuốn hút triệu view",
        "denoise": True,
    },
]

for cv in CUSTOM_VOICES:
    wpath = cv["wav"]
    if wpath.exists():
        t1 = time.time()
        tts.add_voice(
            name=cv["name"],
            ref_audio=str(wpath),
            denoise=cv["denoise"],
            use_ref_codes=True,
            description=cv["description"],
            gender=cv["gender"],
            save=False,
        )
        # Mark featured rank
        if cv["name"] in tts._preset_voices:
            tts._preset_voices[cv["name"]]["featured"] = 1
        print(f"Enrolled '{cv['name']}' in {time.time() - t1:.2f}s")
    else:
        print(f"Missing wav for {cv['name']}: {wpath}")

saved_path = tts.save_voices()
print(f"Saved all enrolled voices to: {saved_path}")

# Also save a backup copy inside our project folder
backup_json = REF_DIR / "voices_v3_turbo_enrolled.json"
backup_json.write_text(Path(saved_path).read_text(encoding="utf-8"), encoding="utf-8")

# Test synthesis with the exact uploaded Vbee voice!
t_syn = time.time()
test_text = "Cúp máy, tôi đứng dựa vào tường, nhìn số dư hơn một triệu đồng trong tài khoản. Tám mươi triệu phải đóng ngay ngày mai."
wav_out = tts.infer(test_text, voice="Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)", apply_watermark=False)
out_test_wav = REF_DIR / "test_cloned_vbee.wav"
sf.write(str(out_test_wav), wav_out, tts.sample_rate)
print(f"Synthesized {len(wav_out)/tts.sample_rate:.2f}s of 48kHz audio in {time.time() - t_syn:.2f}s -> {out_test_wav}")
