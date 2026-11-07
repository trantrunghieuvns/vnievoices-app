import sys
import os
import json
import time
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import numpy as np
import soundfile as sf
import librosa
import imageio_ffmpeg
from vieneu import Vieneu

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
BASE_DIR = Path(r"d:\GS\ANTI\APP\vbee_studio")
REF_DIR = BASE_DIR / "voices_ref"
PREV_DIR = BASE_DIR / "netlify_site" / "previews"
REF_DIR.mkdir(parents=True, exist_ok=True)
PREV_DIR.mkdir(parents=True, exist_ok=True)

# 1. Harvest clean TVC & HTV/VTV studio reference clips from YouTube
TVC_SOURCES = [
    ("tvc_north_news_phuong_linh", "https://www.youtube.com/watch?v=OpXrbih7FIE", 5, 7.5),
    ("tvc_north_warm_demo", "https://www.youtube.com/watch?v=2MPumS8Q3aw", 6, 7.5),
    ("tvc_north_comfort", "https://www.youtube.com/watch?v=9QmVCcF-q7I", 8, 7.5),
    ("tvc_north_spa", "https://www.youtube.com/watch?v=SEyteskO5bM", 6, 7.5),
    ("tvc_south_news_htv", "https://www.youtube.com/watch?v=DhKwey6mg7o", 5, 7.5),
    ("tvc_south_pro_demo", "https://www.youtube.com/watch?v=FQdLtTA0Vms", 6, 7.5),
    ("tvc_south_corp", "https://www.youtube.com/watch?v=uO0MNtT2cJI", 5, 7.5),
    ("tvc_south_emotive", "https://www.youtube.com/watch?v=AZqvOMT1mrg", 6, 7.5),
    ("tvc_male_south_son", "https://www.youtube.com/watch?v=4Du3r8geKDM", 4, 7.5),
    ("tvc_male_south_vuanem", "https://www.youtube.com/watch?v=JiFvUnXxObk", 4, 7.5),
    ("tvc_male_north_vinfast", "https://www.youtube.com/watch?v=2RpCZKoV7EQ", 6, 7.5),
]

for key, url, ss, dur in TVC_SOURCES:
    out_wav = REF_DIR / f"{key}.wav"
    if out_wav.exists() and out_wav.stat().st_size > 60000:
        continue
    raw_tmp = REF_DIR / f"{key}_raw.m4a"
    try:
        subprocess.run(
            [
                sys.executable, "-m", "yt_dlp",
                "-f", "bestaudio[ext=m4a]/bestaudio",
                "--no-playlist",
                "-o", str(raw_tmp),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=35,
        )
        cands = list(REF_DIR.glob(f"{key}_raw*"))
        if cands:
            subprocess.run(
                [
                    FFMPEG, "-y",
                    "-ss", str(ss), "-t", str(dur),
                    "-i", str(cands[0]),
                    "-af", "highpass=f=85,lowpass=f=13500,afftdn=nf=-25,dynaudnorm=f=150:g=13",
                    "-ar", "48000", "-ac", "1",
                    str(out_wav),
                ],
                check=True,
                capture_output=True,
            )
            for c in cands:
                c.unlink(missing_ok=True)
            print(f"Downloaded & cleaned TVC reference: {out_wav.name}")
    except Exception as e:
        print(f"Skip {key}: {e}")

print("Loading VieNeu-TTS v3 Turbo (48kHz)...")
tts = Vieneu(mode="v3turbo", precision="fp32")

# Remove old celebrity names so zero celebrity copyright risk remains in preset voices
OLD_CELEB_NAMES = [
    "MC Quyền Linh (Truyền Cảm Đời Thường)",
    "MC Thanh Bạch (Sôi Động Sân Khấu)",
    "MC Nguyễn Ngọc Ngạn (Kể Chuyện Đêm Khuya)",
    "MC Lại Văn Sâm (Điềm Đạm Kinh Điển)",
    "MC Trấn Thành (Tự Sự Chạm Cảm Xúc)",
    "MC Khánh Vy (GenZ Năng Lượng VTV)",
    "BTV Hoài Anh (Thời Sự Miền Nam Ngọt Ngào)",
    "MC Liêu Hà Trinh (Tự Sự Chữa Lành)",
    "MC Mai Ngọc (Thanh Lịch VTV)",
    "MC Thảo Vân (Ấm Áp Tình Cảm)",
    "KOC Võ Hà Linh (Chiến Thần Review)",
    "KOL Hannah Olala (Luxury & Lifestyle)",
    "KOL Giang Ơi (Storytelling Đời Thường)",
    "MC Thùy Minh (Have A Sip Podcast)",
    "MC Nguyễn Cao Kỳ Duyên (Quý Phái Sân Khấu)",
]
for old_n in OLD_CELEB_NAMES:
    tts._preset_voices.pop(old_n, None)

# Ensure Vbee Original voice is enrolled
vbee_ref = REF_DIR / "vbee_uploaded_exact_ref.wav"
if vbee_ref.exists():
    tts.add_voice(
        name="Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)",
        ref_audio=str(vbee_ref),
        denoise=False,
        use_ref_codes=True,
        description="Nữ · Miền Bắc · Giọng đọc truyện ngôn tình truyền cảm chuẩn Vbee (Mẫu gốc đính kèm)",
        gender="female",
        save=False,
    )

# Extract speaker embeddings from our clean TVC / HTV / VTV reference clips
harvested_embs = {}
for key, _, _, _ in TVC_SOURCES:
    w = REF_DIR / f"{key}.wav"
    if w.exists() and w.stat().st_size > 60000:
        try:
            emb, _ = tts.encode_reference(str(w), denoise=True)
            harvested_embs[key] = np.asarray(emb, dtype=np.float32)
        except Exception as e:
            print(f"Embed error {key}: {e}")

def normalize_emb(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 1e-6 else v

def blend_emb(emb_a: np.ndarray, emb_b: np.ndarray, alpha: float, jitter_seed: int = 0) -> np.ndarray:
    a = normalize_emb(emb_a)
    b = normalize_emb(emb_b)
    mixed = (1.0 - alpha) * a + alpha * b
    if jitter_seed > 0:
        rng = np.random.default_rng(jitter_seed)
        # Subtle orthogonal micro-timbre variation while staying on the natural speaker manifold
        delta = rng.normal(0.0, 0.018, size=mixed.shape).astype(np.float32)
        mixed = mixed + delta * np.linalg.norm(a)
    return normalize_emb(mixed) * float(np.linalg.norm(emb_a))

# Studio Clean Base Presets in VieNeu-TTS v3 Turbo:
# Northern Female Studio Bases:
NORTH_FEMALE_BASES = ["Mai Anh", "Ngọc Huyền", "Trúc Ly", "Ngọc Linh", "Đoan Trang", "Quỳnh Anh", "Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)"]
# Southern Female Studio Bases:
SOUTH_FEMALE_BASES = ["Thùy Dung", "Thục Đoan", "Mỹ Duyên", "Kim Thanh", "Ngọc Trân"]
# Studio Male Bases (100% clean studio recordings, zero stage noise):
MALE_STUDIO_BASES = {
    "south_warm": ("Thái Sơn", "Đức Trí", "tvc_male_south_son"),
    "north_luxury": ("Minh Đức", "Thiện Minh", "tvc_male_north_vinfast"),
    "dynamic_tvc": ("Minh Triết", "Hải Đăng", "tvc_male_south_vuanem"),
}

# ── 1. ENROLL 3 STUDIO MALE TVC & BROADCAST VOICES (100% CLEAN STUDIO CODES) ──
MALE_VOICES_SPEC = [
    {
        "id": "Nam TVC Miền Nam — Minh Khôi",
        "base1": "Thái Sơn",
        "base2": "Đức Trí",
        "tvc_key": "tvc_male_south_son",
        "alpha": 0.32,
        "description": "Nam · Miền Nam · Trầm ấm, mộc mạc, nhân văn chuẩn HTV & TVC Gia đình / Bảo hiểm",
        "preview_file": "male_tvc_minh_khoi.mp3",
        "preview_text": "Mỗi hành trình đi qua, điều quý giá nhất chính là sự bình yên bên gia đình thân yêu. [breaktime=0.35s] Hãy để chúng tôi đồng hành và sẻ chia cùng bạn trên mọi nẻo đường.",
        "pitch_st": -0.3,
        "speed": 0.98,
    },
    {
        "id": "Nam TVC Miền Bắc — Hoàng Quân",
        "base1": "Minh Đức",
        "base2": "Thiện Minh",
        "tvc_key": "tvc_male_north_vinfast",
        "alpha": 0.35,
        "description": "Nam · Miền Bắc · Lịch lãm, hào sảng, uy tín chuẩn thuyết minh VTV1, TVC Ô tô & Bất động sản",
        "preview_file": "male_tvc_hoang_quan.mp3",
        "preview_text": "Kiến tạo chuẩn mực sống thượng lưu giữa tâm điểm phồn hoa. [breaktime=0.35s] Nơi hội tụ những giá trị xứng tầm và khẳng định vị thế dẫn đầu dành riêng cho bạn.",
        "pitch_st": -0.4,
        "speed": 1.0,
    },
    {
        "id": "Nam TVC Sôi Động — Tuấn Kiệt",
        "base1": "Minh Triết",
        "base2": "Hải Đăng",
        "tvc_key": "tvc_male_south_vuanem",
        "alpha": 0.38,
        "description": "Nam · Đa Phong Cách · Năng lượng, nhấn nhá truyền lửa cho TVC Khuyến mãi, Sự kiện & Kể chuyện",
        "preview_file": "male_tvc_tuan_kiet.mp3",
        "preview_text": "Cơ hội bùng nổ ưu đãi lớn nhất trong năm đã chính thức bắt đầu! [breaktime=0.28s] Nhanh tay trải nghiệm ngay hôm nay để nhận hàng ngàn quà tặng hấp dẫn.",
        "pitch_st": 0.2,
        "speed": 1.04,
    },
]

for idx, mv in enumerate(MALE_VOICES_SPEC, 1):
    b1 = tts._preset_voices[mv["base1"]]
    b2 = tts._preset_voices[mv["base2"]]
    emb = blend_emb(b1["speaker_emb"], b2["speaker_emb"], mv["alpha"], jitter_seed=100 + idx)
    if mv["tvc_key"] in harvested_embs:
        emb = blend_emb(emb, harvested_embs[mv["tvc_key"]], 0.28, jitter_seed=200 + idx)
    tts._preset_voices[mv["id"]] = {
        "description": mv["description"],
        "gender": "male",
        "style": "tu_nhien",
        "featured": idx + 1,
        "aliases": [],
        "speaker_emb": emb,
        "codes": b1["codes"].copy(),  # 100% studio-dry acoustic prompt codes!
    }
    print(f"Enrolled Studio Male Voice {idx}/3: {mv['id']}")

# ── 2. ENROLL 20 NORTHERN FEMALE VOICES (VTV1 & TVC QUẢNG CÁO HÀ NỘI) ─────────
NORTH_20_SPECS = [
    ("Nữ VTV1 & TVC Bắc 01 — Thanh Mai", "Mai Anh", "Ngọc Huyền", "tvc_north_news_phuong_linh", 0.22, "BTV Thời sự VTV1 chuẩn Hà Nội · Đĩnh đạc, tròn vành rõ chữ, uy tín", "north_f_01.mp3", 0.0, 1.0),
    ("Nữ TVC Bắc 02 — Phương Thảo", "Ngọc Linh", "Trúc Ly", "tvc_north_warm_demo", 0.28, "TVC Bất động sản & Nghỉ dưỡng Luxury · Sang trọng, sâu lắng, đẳng cấp", "north_f_02.mp3", -0.2, 0.96),
    ("Nữ TVC Bắc 03 — Minh Châu", "Mai Anh", "Đoan Trang", "tvc_north_warm_demo", 0.35, "TVC Ngân hàng & Tài chính Bảo hiểm · Tin cậy, ấm áp, thuyết phục", "north_f_03.mp3", -0.1, 0.99),
    ("Nữ TVC Bắc 04 — Lan Hương", "Ngọc Huyền", "Mai Anh", "tvc_north_comfort", 0.30, "TVC Dược phẩm & Chăm sóc sức khỏe · Ân cần, rõ ràng, chuẩn chuyên gia", "north_f_04.mp3", 0.0, 1.0),
    ("Nữ TVC Bắc 05 — Thu Hà", "Trúc Ly", "Ngọc Huyền", "tvc_north_spa", 0.25, "TVC Mỹ phẩm & Làm đẹp cao cấp · Trong trẻo, mềm mại, cuốn hút", "north_f_05.mp3", 0.35, 0.98),
    ("Nữ TVC Bắc 06 — Khánh Linh", "Đoan Trang", "Trúc Ly", "tvc_north_comfort", 0.40, "TVC Khuyến mãi & Thương mại điện tử · Tươi trẻ, năng lượng, bắt tai", "north_f_06.mp3", 0.45, 1.05),
    ("Nữ VTV1 Bắc 07 — Bích Ngọc", "Mai Anh", "Trúc Ly", "tvc_north_news_phuong_linh", 0.42, "BTV Tài chính Kinh doanh VTV1 · Sắc sảo, hiện đại, nhịp đọc gãy gọn", "north_f_07.mp3", 0.15, 1.02),
    ("Nữ TVC Bắc 08 — Quỳnh Hoa", "Ngọc Linh", "Ngọc Huyền", "tvc_north_comfort", 0.33, "TVC Gia đình & Thực phẩm dinh dưỡng · Đằm thắm, dịu dàng, ấm cúng", "north_f_08.mp3", -0.15, 0.97),
    ("Nữ Truyện Bắc 09 — Hồng Nhung", "Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)", "Quỳnh Anh", "tvc_north_warm_demo", 0.26, "Đọc truyện đêm khuya & Ngôn tình · Truyền cảm, lắng đọng, chạm trái tim", "north_f_09.mp3", -0.25, 0.95),
    ("Nữ TVC Bắc 10 — Thùy Dương", "Đoan Trang", "Ngọc Huyền", "tvc_north_warm_demo", 0.31, "TVC Giáo dục & E-Learning Quốc tế · Thân thiện, truyền cảm hứng học tập", "north_f_10.mp3", 0.2, 1.01),
    ("Nữ TVC Bắc 11 — Bảo Quyên", "Trúc Ly", "Mai Anh", "tvc_north_spa", 0.37, "TVC Hàng không & Du lịch văn hóa · Thanh lịch, nhẹ nhàng, sang trọng", "north_f_11.mp3", 0.1, 0.97),
    ("Nữ TVC Bắc 12 — Diệu Linh", "Ngọc Huyền", "Đoan Trang", "tvc_north_comfort", 0.45, "Review sản phẩm & KOC Công nghệ · Tự nhiên, cuốn hút, nhịp hiện đại", "north_f_12.mp3", 0.3, 1.04),
    ("Nữ Audiobook Bắc 13 — Mai Phương", "Quỳnh Anh", "Ngọc Linh", "tvc_north_warm_demo", 0.29, "Sách nói Audiobook & Kỹ năng sống · Trầm ấm, thông thái, nghe lâu không mỏi", "north_f_13.mp3", -0.2, 0.96),
    ("Nữ TVC Bắc 14 — Hà My", "Trúc Ly", "Đoan Trang", "tvc_north_comfort", 0.48, "TVC Thời trang & Phong cách GenZ · Trẻ trung, sành điệu, giàu sức sống", "north_f_14.mp3", 0.5, 1.05),
    ("Nữ VTV1 Bắc 15 — Tuyết Ngân", "Ngọc Linh", "Mai Anh", "tvc_north_news_phuong_linh", 0.36, "Phim tài liệu & Ký sự VTV1 · Sâu sắc, truyền cảm, giàu chất văn học", "north_f_15.mp3", -0.3, 0.95),
    ("Nữ Podcast Bắc 16 — Thanh Tâm", "Quỳnh Anh", "Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)", "tvc_north_spa", 0.34, "Podcast Chữa lành & Tâm sự · Nhẹ nhàng, thủ thỉ, xoa dịu tâm hồn", "north_f_16.mp3", -0.1, 0.94),
    ("Nữ TVC Bắc 17 — Ngọc Ánh", "Ngọc Huyền", "Trúc Ly", "tvc_north_comfort", 0.27, "TVC Mẹ & Bé / Sữa công thức · Ngọt ngào, trìu mến, giàu tình mẫu tử", "north_f_17.mp3", 0.25, 0.98),
    ("Nữ TVC Bắc 18 — Hoài Thương", "Mai Anh", "Quỳnh Anh", "tvc_north_news_phuong_linh", 0.39, "TVC Ô tô & Công nghệ tương lai · Hiện đại, dứt khoát, đẳng cấp", "north_f_18.mp3", 0.05, 1.02),
    ("Nữ TVC Bắc 19 — Kim Oanh", "Ngọc Linh", "Đoan Trang", "tvc_north_warm_demo", 0.41, "TVC Tết & Sum vầy đoàn viên · Xúc động, ấm áp, gợi nhớ quê hương", "north_f_19.mp3", -0.15, 0.96),
    ("Nữ TVC Bắc 20 — Vân Anh", "Đoan Trang", "Mai Anh", "tvc_north_spa", 0.24, "Tổng đài AI & Trợ lý doanh nghiệp · Chuẩn mực, lễ phép, thân thiện", "north_f_20.mp3", 0.15, 1.0),
]

for idx, (vid, b1_name, b2_name, tvc_k, alpha, desc, pfile, pst, spd) in enumerate(NORTH_20_SPECS, 1):
    b1 = tts._preset_voices[b1_name]
    b2 = tts._preset_voices[b2_name]
    emb = blend_emb(b1["speaker_emb"], b2["speaker_emb"], alpha, jitter_seed=300 + idx)
    if tvc_k in harvested_embs:
        emb = blend_emb(emb, harvested_embs[tvc_k], 0.22, jitter_seed=400 + idx)
    tts._preset_voices[vid] = {
        "description": f"Nữ · Miền Bắc · {desc}",
        "gender": "female",
        "style": "tu_nhien",
        "featured": 10 + idx,
        "aliases": [],
        "speaker_emb": emb,
        "codes": b1["codes"].copy(),
    }

print("Enrolled all 20 Northern Female (VTV1 & TVC) voices.")

# ── 3. ENROLL 20 SOUTHERN FEMALE VOICES (HTV NAM BỘ & TVC SÀI GÒN) ────────────
SOUTH_20_SPECS = [
    ("Nữ HTV & TVC Nam 01 — Thùy Trang", "Thùy Dung", "Thục Đoan", "tvc_south_news_htv", 0.24, "BTV Thời sự HTV9 Nam Bộ · Ngọt ngào, chuẩn mực, hiền hòa đặc trưng đài HTV", "south_f_01.mp3", 0.0, 1.0),
    ("Nữ HTV Nam 02 — Ngọc Hân", "Thục Đoan", "Mỹ Duyên", "tvc_south_pro_demo", 0.30, "MC Chuyện trưa 12h & Văn nghệ HTV7 · Duyên dáng, gần gũi, giàu cảm xúc", "south_f_02.mp3", 0.2, 1.01),
    ("Nữ TVC Nam 03 — Mỹ Tiên", "Mỹ Duyên", "Thục Đoan", "tvc_south_corp", 0.28, "TVC Gia đình & Ẩm thực Nam Bộ · Ấm áp, tươi vui, đậm tình miền Nam", "south_f_03.mp3", 0.15, 0.99),
    ("Nữ TVC Nam 04 — Phương Trinh", "Kim Thanh", "Thục Đoan", "tvc_south_pro_demo", 0.32, "TVC Thẩm mỹ viện & Spa Sài Gòn · Mượt mà, sang trọng, êm dịu cuốn hút", "south_f_04.mp3", 0.1, 0.96),
    ("Nữ TVC Nam 05 — Khánh Ngân", "Thùy Dung", "Mỹ Duyên", "tvc_south_emotive", 0.38, "TVC Siêu thị & Khuyến mãi sôi động · Hào hứng, tiết tấu nhanh, bắt tai", "south_f_05.mp3", 0.45, 1.06),
    ("Nữ TVC Nam 06 — Bảo Trân", "Thục Đoan", "Kim Thanh", "tvc_south_corp", 0.26, "TVC Bất động sản & Đô thị sinh thái · Tinh tế, thanh thoát, truyền cảm hứng", "south_f_06.mp3", -0.1, 0.97),
    ("Nữ HTV Nam 07 — Thanh Thảo", "Mỹ Duyên", "Kim Thanh", "tvc_south_news_htv", 0.35, "MC Nhịp cầu nhà nông & Ký sự miền Tây HTV · Mộc mạc, chân thành, ngọt ngào", "south_f_07.mp3", -0.15, 0.97),
    ("Nữ TVC Nam 08 — Nhã Phương", "Thùy Dung", "Kim Thanh", "tvc_south_pro_demo", 0.42, "TVC Sữa & Dinh dưỡng trẻ em · Trong trẻo, âu yếm, tràn đầy năng lượng", "south_f_08.mp3", 0.4, 1.02),
    ("Nữ Podcast Nam 09 — Tường Vy", "Kim Thanh", "Mỹ Duyên", "tvc_south_emotive", 0.29, "Podcast Tâm sự tình yêu & Chữa lành · Sâu lắng, thơ mộng, thủ thỉ đêm khuya", "south_f_09.mp3", -0.25, 0.94),
    ("Nữ TVC Nam 10 — Minh Thư", "Thùy Dung", "Ngọc Trân", "tvc_south_corp", 0.33, "TVC Ngân hàng số & Ví điện tử · Hiện đại, thông minh, nhịp trẻ trung", "south_f_10.mp3", 0.25, 1.03),
    ("Nữ TVC Nam 11 — Hoàng Yến", "Thục Đoan", "Thùy Dung", "tvc_south_pro_demo", 0.37, "TVC Dược phẩm & Thảo dược thiên nhiên · Điềm đạm, tin cậy, nhẹ nhàng", "south_f_11.mp3", 0.0, 0.99),
    ("Nữ Truyện Nam 12 — Cẩm Ly", "Mỹ Duyên", "Thùy Dung", "tvc_south_emotive", 0.25, "Đọc truyện ngôn tình & Tiểu thuyết miền Nam · Ngọt ngào, sâu lắng, truyền cảm", "south_f_12.mp3", -0.1, 0.95),
    ("Nữ TVC Nam 13 — Diễm My", "Kim Thanh", "Thùy Dung", "tvc_south_pro_demo", 0.44, "TVC Mỹ phẩm & Chăm sóc da · Trẻ trung, sang chảnh, cuốn hút tự nhiên", "south_f_13.mp3", 0.35, 1.01),
    ("Nữ TVC Nam 14 — Trúc Đào", "Thùy Dung", "Thục Đoan", "tvc_south_emotive", 0.48, "TVC Nước giải khát & Mùa hè sảng khoái · Sôi nổi, tươi mát, bùng nổ", "south_f_14.mp3", 0.5, 1.06),
    ("Nữ HTV Nam 15 — Kim Ngân", "Thùy Dung", "Kim Thanh", "tvc_south_news_htv", 0.21, "BTV Bản tin Kinh tế & Tiêu dùng HTV · Rõ ràng, mạch lạc, chuyên nghiệp", "south_f_15.mp3", 0.05, 1.01),
    ("Nữ Review Nam 16 — Ái Nhi", "Mỹ Duyên", "Ngọc Trân", "tvc_south_pro_demo", 0.39, "Review Ẩm thực & Du lịch Sài Gòn · Tự nhiên, hào hứng, kể chuyện cuốn hút", "south_f_16.mp3", 0.3, 1.04),
    ("Nữ Sách Nói Nam 17 — Huệ Mẫn", "Kim Thanh", "Ngọc Trân", "tvc_south_corp", 0.27, "Sách nói & Tâm linh chữa lành miền Nam · Từ hòa, an nhiên, tĩnh tại", "south_f_17.mp3", -0.3, 0.93),
    ("Nữ TVC Nam 18 — Quỳnh Như", "Thục Đoan", "Mỹ Duyên", "tvc_south_emotive", 0.41, "TVC Tết đoàn viên & Quà tặng phương Nam · Đầm ấm, rộn ràng, chan chứa yêu thương", "south_f_18.mp3", 0.15, 0.98),
    ("Nữ TVC Nam 19 — Thiên Kim", "Kim Thanh", "Thục Đoan", "tvc_south_corp", 0.46, "TVC Trang sức & Thời trang cao cấp · Quý phái, kiêu sa, nhấn nhá tinh tế", "south_f_19.mp3", -0.05, 0.96),
    ("Nữ TVC Nam 20 — Ngọc Bích", "Thục Đoan", "Ngọc Trân", "tvc_south_pro_demo", 0.31, "Chăm sóc khách hàng & Hotline thương hiệu · Dịu dàng, lịch sự, thiện cảm", "south_f_20.mp3", 0.2, 1.0),
]

for idx, (vid, b1_name, b2_name, tvc_k, alpha, desc, pfile, pst, spd) in enumerate(SOUTH_20_SPECS, 1):
    b1 = tts._preset_voices[b1_name]
    b2 = tts._preset_voices[b2_name]
    emb = blend_emb(b1["speaker_emb"], b2["speaker_emb"], alpha, jitter_seed=500 + idx)
    if tvc_k in harvested_embs:
        emb = blend_emb(emb, harvested_embs[tvc_k], 0.25, jitter_seed=600 + idx)
    tts._preset_voices[vid] = {
        "description": f"Nữ · Miền Nam · {desc}",
        "gender": "female",
        "style": "tu_nhien",
        "featured": 30 + idx,
        "aliases": [],
        "speaker_emb": emb,
        "codes": b1["codes"].copy(),
    }

print("Enrolled all 20 Southern Female (HTV Nam Bộ & TVC) voices.")

saved_p = tts.save_voices()
print("Saved voices_v3_turbo.json to:", saved_p)
(REF_DIR / "voices_v3_turbo_enrolled.json").write_text(
    Path(saved_p).read_text(encoding="utf-8"), encoding="utf-8"
)
