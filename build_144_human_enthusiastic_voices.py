import sys
import os
import json
import time
import shutil
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import numpy as np
import soundfile as sf
import imageio_ffmpeg
from vieneu import Vieneu

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
BASE_DIR = Path(r"d:\GS\ANTI\APP\vbee_studio")
REF_DIR = BASE_DIR / "voices_ref"
PREV_DIR = BASE_DIR / "netlify_site" / "previews"
REF_DIR.mkdir(parents=True, exist_ok=True)
PREV_DIR.mkdir(parents=True, exist_ok=True)

print("Loading VieNeu-TTS v3 Turbo (48kHz) to enroll 100 NEW Enthusiastic Human Voices (30 Male + 70 Female -> 144 Total)...")
tts = Vieneu(mode="v3turbo", precision="fp32")

# Load harvested TVC x-vector embeddings from voices_ref
TVC_KEYS = [
    "tvc_north_news_phuong_linh",
    "tvc_north_warm_demo",
    "tvc_north_comfort",
    "tvc_north_spa",
    "tvc_south_news_htv",
    "tvc_south_pro_demo",
    "tvc_south_corp",
    "tvc_south_emotive",
    "tvc_male_south_son",
    "tvc_male_south_vuanem",
    "tvc_male_north_vinfast",
]

harvested_embs = {}
for k in TVC_KEYS:
    w = REF_DIR / f"{k}.wav"
    if w.exists() and w.stat().st_size > 40000:
        try:
            emb, _ = tts.encode_reference(str(w), denoise=True)
            harvested_embs[k] = np.asarray(emb, dtype=np.float32)
        except Exception as e:
            print(f"Warn embed {k}: {e}")


def normalize_emb(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 1e-6 else v


def blend_multi_emb(embs_and_weights: list, jitter_seed: int = 0) -> np.ndarray:
    """Spherical-linear manifold blend across multiple studio & TVC speaker embeddings."""
    ref_norm = float(np.linalg.norm(np.asarray(embs_and_weights[0][0], dtype=np.float32)))
    acc = np.zeros(192, dtype=np.float32)
    for emb, w in embs_and_weights:
        acc += float(w) * normalize_emb(emb)
    if jitter_seed > 0:
        rng = np.random.default_rng(jitter_seed)
        delta = rng.normal(0.0, 0.022, size=acc.shape).astype(np.float32)
        acc = acc + delta
    return normalize_emb(acc) * ref_norm


# ── 30 NEW ENTHUSIASTIC MALE VOICES (15 MIỀN NAM + 15 MIỀN BẮC) ───────────────
# Designed specifically to be vibrant, energetic, non-robotic, with strong final-clause ("khoản cuối") human conviction
NEW_30_MALES = [
    # 15 Nam Miền Nam Hào Hứng & Truyền Lửa (01..15)
    ("Nam Hào Hứng 01 — Gia Huy (TVC Bùng Nổ)", "Minh Triết", "Thái Sơn", "tvc_male_south_vuanem", "Miền Nam", "TVC Khuyến Mãi", "Hào hứng, bùng nổ năng lượng, nhấn khoản cuối cực sung", "#f59e0b", 0.15, 1.06),
    ("Nam Hào Hứng 02 — Bảo Long (MC Sự Kiện)", "Thái Sơn", "Minh Triết", "tvc_male_south_son", "Miền Nam", "MC Gala & Event", "Sôi nổi, truyền lửa sân khấu, dứt khoát và cuốn hút", "#ea580c", 0.25, 1.07),
    ("Nam Hào Hứng 03 — Quốc Bảo (Review Công Nghệ)", "Minh Triết", "Adam", "tvc_male_south_vuanem", "Miền Nam", "Review Tech", "Trẻ trung, nhịp nhanh hiện đại, nhấn mạnh ý hay tự nhiên", "#0284c7", 0.10, 1.05),
    ("Nam Hào Hứng 04 — Đăng Khoa (TVC Thể Thao)", "Đức Trí", "Minh Triết", "tvc_male_south_son", "Miền Nam", "TVC Sport & Nước Tăng Lực", "Mạnh mẽ, khỏe khoắn, kết câu giàu nội lực nam tính", "#dc2626", -0.10, 1.06),
    ("Nam Hào Hứng 05 — Anh Tuấn (Livestream Chốt Đơn)", "Adam", "Minh Triết", "tvc_male_south_vuanem", "Miền Nam", "Livestream & Sale", "Hoạt ngôn, bắt tai, thúc giục hành động cuối câu cực đỉnh", "#e11d48", 0.30, 1.08),
    ("Nam Hào Hứng 06 — Trọng Nhân (TVC Ô Tô & Xe Máy)", "Thái Sơn", "Đức Trí", "tvc_male_south_son", "Miền Nam", "TVC Auto", "Sang trọng, hào sảng, nhấn nhá điểm rơi cuối câu đầy bản lĩnh", "#2563eb", -0.20, 1.03),
    ("Nam Hào Hứng 07 — Chí Thành (BTV Thể Thao HTV)", "Minh Triết", "Đức Trí", "tvc_male_south_vuanem", "Miền Nam", "Bình Luận & Bản Tin", "Nhịp điệu sôi động, hào hứng như bình luận viên trực tiếp", "#16a34a", 0.20, 1.06),
    ("Nam Hào Hứng 08 — Minh Nhật (Vlogger Ẩm Thực)", "Adam", "Thái Sơn", "tvc_male_south_son", "Miền Nam", "Vlog & Food Review", "Gần gũi, tấm tắc khen ngon, cảm thán tự nhiên như đời thực", "#d97706", 0.18, 1.05),
    ("Nam Hào Hứng 09 — Tấn Phát (TVC Điện Máy)", "Minh Triết", "Quang Sơn", "tvc_male_south_vuanem", "Miền Nam", "TVC Siêu Thị Điện Máy", "Rõ ràng, vang sáng, chốt giá và ưu đãi cuối câu cực kỳ thuyết phục", "#ef4444", 0.28, 1.07),
    ("Nam Hào Hứng 10 — Khắc Việt (Diễn Giả Truyền Cảm Hứng)", "Thái Sơn", "Adam", "tvc_male_south_son", "Miền Nam", "Motivational & Coaching", "Truyền cảm hứng mãnh liệt, nhấn mạnh từ khóa và kết câu sâu sắc", "#7c3aed", -0.05, 1.03),
    ("Nam Hào Hứng 11 — Hải Nam (TVC Ngân Hàng Số)", "Minh Triết", "Thái Sơn", "tvc_male_south_vuanem", "Miền Nam", "Fintech & App", "Năng động, thông minh, nhịp đọc tươi sáng hiện đại", "#0891b2", 0.12, 1.04),
    ("Nam Hào Hứng 12 — Hoàng Phúc (TVC Bia & Lễ Hội)", "Đức Trí", "Minh Triết", "tvc_male_south_son", "Miền Nam", "TVC Lễ Hội & Bia", "Sảng khoái, hào hùng, khuấy động không khí tưng bừng", "#ca8a04", 0.05, 1.06),
    ("Nam Hào Hứng 13 — Thiên Ân (Podcast Khởi Nghiệp)", "Thái Sơn", "Quang Sơn", "tvc_male_south_son", "Miền Nam", "Podcast & Business", "Đĩnh đạc, cuốn hút, nhấn nhá các ý tưởng đắt giá cực kỳ có hồn", "#0d9488", -0.15, 1.02),
    ("Nam Hào Hứng 14 — Duy Khánh (MC Gameshow Giải Trí)", "Adam", "Minh Triết", "tvc_male_south_vuanem", "Miền Nam", "MC Giải Trí", "Tươi vui, dí dỏm, giàu biểu cảm và năng lượng tích cực", "#f97316", 0.35, 1.07),
    ("Nam Hào Hứng 15 — Thành Đạt (TVC Bất Động Sản Nam Bộ)", "Thái Sơn", "Đức Trí", "tvc_male_south_son", "Miền Nam", "TVC BĐS", "Ấm áp, tầm nhìn lớn, nhấn mạnh giá trị đầu tư ở khoản cuối câu", "#059669", -0.18, 1.02),

    # 15 Nam Miền Bắc Hào Hứng & Uy Lực (16..30)
    ("Nam Hào Hứng 16 — Quang Vinh (TVC Thương Hiệu Quốc Gia)", "Hải Đăng", "Minh Đức", "tvc_male_north_vinfast", "Miền Bắc", "TVC Quốc Gia", "Hào sảng, tự hào, nhấn kết câu vang vọng và đầy khí chất", "#0284c7", 0.05, 1.04),
    ("Nam Hào Hứng 17 — Đức Anh (Review Xe & Công Nghệ)", "Xuân Vĩnh", "Hải Đăng", "tvc_male_north_vinfast", "Miền Bắc", "Tech & Auto Review", "Trẻ trung, sắc bén, hào hứng phân tích những điểm đắt giá", "#2563eb", 0.18, 1.05),
    ("Nam Hào Hứng 18 — Mạnh Hùng (TVC Khuyến Mãi Hà Nội)", "Hải Đăng", "Quốc Tuấn", "tvc_male_north_vinfast", "Miền Bắc", "TVC Sale Bùng Nổ", "Tiết tấu nhanh, sôi nổi, cuốn người nghe vào ưu đãi ngay lập tức", "#e11d48", 0.25, 1.07),
    ("Nam Hào Hứng 19 — Trung Kiên (MC Sự Kiện & Lễ Mở Bán)", "Minh Đức", "Xuân Vĩnh", "tvc_male_north_vinfast", "Miền Bắc", "MC Mở Bán BĐS", "Lịch lãm, nhiệt huyết, đẩy cao trào ở khoản cuối mỗi đoạn", "#d97706", 0.10, 1.05),
    ("Nam Hào Hứng 20 — Việt Hoàng (BTV Bản Tin Chuyển Động)", "Minh Đức", "Hải Đăng", "tvc_male_north_vinfast", "Miền Bắc", "BTV Năng Động", "Linh hoạt, hiện đại, nhấn nhá thông tin trọng tâm cực kỳ gãy gọn", "#0369a1", 0.08, 1.04),
    ("Nam Hào Hứng 21 — Thái Hòa (Storyteller & Phim Tài Liệu)", "Thiện Minh", "Minh Đức", "tvc_male_north_vinfast", "Miền Bắc", "Kể Chuyện Điện Ảnh", "Giàu kịch tính, có chiều sâu, nhấn chữ cuối câu chạm thấu cảm xúc", "#7c3aed", -0.22, 1.00),
    ("Nam Hào Hứng 22 — Tuấn Hưng (TVC Du Lịch & Hàng Không)", "Xuân Vĩnh", "Phạm Tuyên", "tvc_male_north_vinfast", "Miền Bắc", "TVC Du Lịch", "Tươi mới, phóng khoáng, khơi dậy cảm hứng khám phá", "#0891b2", 0.15, 1.04),
    ("Nam Hào Hứng 23 — Khôi Nguyên (KOC Sáng Tạo Nội Dung)", "Hải Đăng", "Adam bựa", "tvc_male_north_vinfast", "Miền Bắc", "TikTok & Reels Creator", "Tự nhiên 100% như nói chuyện trực tiếp, bắt trend, không chút máy móc", "#f43f5e", 0.30, 1.07),
    ("Nam Hào Hứng 24 — Đình Phong (TVC Tài Chính & Chứng Khoán)", "Minh Đức", "Quốc Tuấn", "tvc_male_north_vinfast", "Miền Bắc", "TVC Đầu Tư", "Quyết đoán, thông thái, nhấn mạnh con số và cơ hội sinh lời", "#0d9488", -0.08, 1.03),
    ("Nam Hào Hứng 25 — Minh Quân (MC Radio & Podcast Sáng)", "Xuân Vĩnh", "Thanh Bình", "tvc_male_north_vinfast", "Miền Bắc", "Radio Host", "Ấm áp, tràn đầy năng lượng buổi sáng, nhịp thở tự nhiên", "#f59e0b", 0.12, 1.04),
    ("Nam Hào Hứng 26 — Nam Khánh (TVC Giáo Dục & Học Viện)", "Hải Đăng", "Thiện Minh", "tvc_male_north_vinfast", "Miền Bắc", "TVC EdTech", "Nhiệt tình, truyền động lực học tập và bứt phá bản thân", "#10b981", 0.16, 1.05),
    ("Nam Hào Hứng 27 — Bá Tùng (TVC Dược Phẩm & Thể Lực)", "Quốc Tuấn", "Minh Đức", "tvc_male_north_vinfast", "Miền Bắc", "TVC Sức Khỏe Nam Giới", "Vững chãi, khỏe khoắn, tạo niềm tin tuyệt đối ở câu kết", "#16a34a", -0.12, 1.03),
    ("Nam Hào Hứng 28 — Hoàng Bách (Vlogger Phong Cách Sống)", "Phạm Tuyên", "Xuân Vĩnh", "tvc_male_north_vinfast", "Miền Bắc", "Lifestyle Vlog", "Phóng khoáng, cởi mở, có tiếng lấy hơi và nhấn nhá rất đời", "#6366f1", 0.08, 1.04),
    ("Nam Hào Hứng 29 — Nhật Minh (TVC Thương Mại Điện Tử)", "Hải Đăng", "Xuân Vĩnh", "tvc_male_north_vinfast", "Miền Bắc", "E-Commerce Sale", "Nhanh, gọn, bùng nổ cảm xúc mua sắm ở khoản cuối câu", "#ec4899", 0.28, 1.08),
    ("Nam Hào Hứng 30 — Vũ Long (Diễn Giả Kinh Doanh Chiến Lược)", "Thiền Tâm Đức", "Minh Đức", "tvc_male_north_vinfast", "Miền Bắc", "Business Keynote", "Trầm hùng, uy lực, mỗi câu chốt đều đanh thép và truyền lửa", "#1e293b", -0.25, 1.01),
]

# ── 70 NEW ENTHUSIASTIC FEMALE VOICES (35 MIỀN NAM + 35 MIỀN BẮC) ─────────────
SOUTH_F_NAMES = [
    ("Nữ Hào Hứng Nam 01 — Thảo Nhi (TVC Sale Bùng Nổ)", "Thùy Dung", "Mỹ Duyên", "tvc_south_emotive", "TVC Mega Sale", "Rạng rỡ, hào hứng cực độ, chốt ưu đãi cuối câu siêu cuốn", "#f43f5e", 0.35, 1.07),
    ("Nữ Hào Hứng Nam 02 — Yến Trang (MC Sự Kiện Sài Gòn)", "Thục Đoan", "Thùy Dung", "tvc_south_pro_demo", "MC Event", "Tươi tắn, duyên dáng, truyền năng lượng tích cực từng câu chữ", "#ec4899", 0.25, 1.05),
    ("Nữ Hào Hứng Nam 03 — Lan Anh (Livestream Mỹ Phẩm)", "Mỹ Duyên", "Thùy Dung", "tvc_south_emotive", "Livestream Beauty", "Ngọt ngào, nịnh tai, nhấn mạnh công dụng và giá hời cực khéo", "#db2777", 0.40, 1.07),
    ("Nữ Hào Hứng Nam 04 — Minh Ngọc (TVC Nước Giải Khát)", "Thùy Dung", "Ngọc Trân", "tvc_south_emotive", "TVC Beverage", "Tươi mát, sảng khoái, bật tung năng lượng mùa hè ở khoản cuối", "#06b6d4", 0.45, 1.06),
    ("Nữ Hào Hứng Nam 05 — Quỳnh Hương (BTV Chào Buổi Sáng HTV)", "Thùy Dung", "Thục Đoan", "tvc_south_news_htv", "BTV Buổi Sáng", "Trong trẻo, tràn đầy sức sống ngày mới, nhịp đọc linh hoạt", "#0284c7", 0.18, 1.04),
    ("Nữ Hào Hứng Nam 06 — Tuyết Mai (Review Ẩm Thực Đường Phố)", "Mỹ Duyên", "Ngọc Trân", "tvc_south_pro_demo", "Food Reviewer", "Hào hứng, xuýt xoa tự nhiên, nghe là thấy thèm ngay lập tức", "#f97316", 0.32, 1.06),
    ("Nữ Hào Hứng Nam 07 — Gia Hân (TVC Thời Trang & Lookbook)", "Kim Thanh", "Thùy Dung", "tvc_south_pro_demo", "TVC Fashion", "Sành điệu, hiện đại, nhấn nhá cá tính ở cuối mỗi câu", "#8b5cf6", 0.22, 1.04),
    ("Nữ Hào Hứng Nam 08 — Thiên Thanh (TVC Sữa & Năng Lượng Trẻ)", "Thùy Dung", "Mỹ Duyên", "tvc_south_corp", "TVC Sữa & Dinh Dưỡng", "Vui tươi, âu yếm, truyền cảm hứng khỏe mạnh cho bé và gia đình", "#10b981", 0.30, 1.04),
    ("Nữ Hào Hứng Nam 09 — Kiều Trinh (KOC Unbox & Săn Deal)", "Mỹ Duyên", "Thùy Dung", "tvc_south_emotive", "KOC Săn Deal", "Nhanh nhẹn, bắt trend, nhấn mạnh điểm ăn tiền của sản phẩm", "#e11d48", 0.38, 1.08),
    ("Nữ Hào Hứng Nam 10 — Nhã Kỳ (TVC Thẩm Mỹ & Luxury Spa)", "Thục Đoan", "Kim Thanh", "tvc_south_corp", "TVC Luxury Spa", "Sang trọng nhưng đầy sức sống, thuyết phục phái đẹp ở câu kết", "#d97706", 0.08, 1.01),
    ("Nữ Hào Hứng Nam 11 — Bích Phương (MC Du Lịch Khám Phá)", "Thùy Dung", "Ngọc Trân", "tvc_south_pro_demo", "MC Travel", "Phóng khoáng, mê hoặc, mời gọi du khách bằng cái kết đầy cảm xúc", "#0891b2", 0.20, 1.04),
    ("Nữ Hào Hứng Nam 12 — Thanh Trúc (TVC Siêu Thị & Gia Dụng)", "Thục Đoan", "Mỹ Duyên", "tvc_south_emotive", "TVC Gia Dụng", "Đảm đang, rộn ràng, chia sẻ bí quyết nội trợ cực kỳ hào hứng", "#ea580c", 0.26, 1.05),
    ("Nữ Hào Hứng Nam 13 — Ngọc Thảo (TikTok & Reels Creator)", "Mỹ Duyên", "Thùy Dung", "tvc_south_pro_demo", "Short Video Voice", "Giọng cười tươi trong lời nói, dứt khoát, không một chút robot", "#f43f5e", 0.42, 1.07),
    ("Nữ Hào Hứng Nam 14 — Hà Tiên (TVC Bất Động Sản Nghỉ Dưỡng)", "Kim Thanh", "Thục Đoan", "tvc_south_corp", "TVC Resort & Villa", "Thanh tao, bay bổng, nâng tầm giá trị sống ở khoản cuối câu", "#0d9488", 0.05, 1.00),
    ("Nữ Hào Hứng Nam 15 — Xuân Nghi (TVC Giáo Dục & Anh Ngữ)", "Thùy Dung", "Kim Thanh", "tvc_south_news_htv", "TVC Anh Ngữ", "Năng động, phát âm chuẩn mực, truyền lửa học tập", "#2563eb", 0.24, 1.05),
    ("Nữ Hào Hứng Nam 16 — Trâm Anh (Podcast Truyền Động Lực)", "Thục Đoan", "Mỹ Duyên", "tvc_south_emotive", "Podcast GenZ", "Chân thành, nhiệt huyết, nhấn mạnh thông điệp tích cực cuối câu", "#9333ea", 0.14, 1.02),
    ("Nữ Hào Hứng Nam 17 — Linh Đan (TVC Điện Thoại & Laptop)", "Thùy Dung", "Ngọc Trân", "tvc_south_corp", "TVC Tech & Mobile", "Trẻ trung, hiện đại, làm nổi bật tính năng đột phá", "#0284c7", 0.28, 1.06),
    ("Nữ Hào Hứng Nam 18 — Mai Thảo (MC Văn Nghệ & Lễ Hội Nam Bộ)", "Mỹ Duyên", "Thục Đoan", "tvc_south_news_htv", "MC Lễ Hội", "Tưng bừng, rộn rã sắc xuân, kết câu ngân vang đầy cảm xúc", "#dc2626", 0.22, 1.04),
    ("Nữ Hào Hứng Nam 19 — Khánh Vân (TVC Hàng Không & Vé Máy Bay)", "Thục Đoan", "Thùy Dung", "tvc_south_pro_demo", "TVC Airlines", "Tươi sáng, thân thiện, chào đón nồng nhiệt như tiếp viên trưởng", "#0369a1", 0.16, 1.03),
    ("Nữ Hào Hứng Nam 20 — Ngọc Diệp (Review Phim & Giải Trí)", "Mỹ Duyên", "Kim Thanh", "tvc_south_emotive", "Movie Recap", "Cuốn hút, kịch tính, nhấn nhá plot twist ở cuối câu cực bén", "#7c3aed", 0.20, 1.06),
    ("Nữ Hào Hứng Nam 21 — Thúy Ngân (TVC Ngân Hàng & Thẻ Tín Dụng)", "Thùy Dung", "Thục Đoan", "tvc_south_corp", "TVC Banking", "Thông minh, lôi cuốn, làm nổi bật đặc quyền hoàn tiền cuối câu", "#059669", 0.15, 1.04),
    ("Nữ Hào Hứng Nam 22 — Bảo Ngọc (TVC Trang Sức Kim Cương)", "Kim Thanh", "Mỹ Duyên", "tvc_south_pro_demo", "TVC Jewelry", "Kiêu sa, lấp lánh, nhấn chữ tinh tế tạo đẳng cấp khác biệt", "#ca8a04", 0.10, 1.01),
    ("Nữ Hào Hứng Nam 23 — Yến Nhi (Livestream Thời Trang Thiết Kế)", "Mỹ Duyên", "Thùy Dung", "tvc_south_emotive", "Live Fashion", "Nhiệt tình tư vấn, giọng nói có nụ cười và nhịp thở sống động", "#ec4899", 0.36, 1.07),
    ("Nữ Hào Hứng Nam 24 — Thanh Hà (TVC Y Tế & Bệnh Viện Quốc Tế)", "Thục Đoan", "Kim Thanh", "tvc_south_news_htv", "TVC Healthcare", "Ấm áp, ân cần, trao trọn niềm tin sức khỏe ở phần kết", "#10b981", 0.08, 1.01),
    ("Nữ Hào Hứng Nam 25 — Minh Khuê (Sách Nói Tư Duy Làm Giàu)", "Thùy Dung", "Kim Thanh", "tvc_south_corp", "Audiobook Kinh Doanh", "Sắc sảo, truyền cảm hứng hành động, nhấn mạnh bài học đắt giá", "#2563eb", 0.12, 1.03),
    ("Nữ Hào Hứng Nam 26 — Hồng Ân (TVC Nước Giặt & Chăm Sóc Nhà)", "Mỹ Duyên", "Thục Đoan", "tvc_south_pro_demo", "TVC FMCG", "Tươi vui, gần gũi, ngân giọng cuối câu đầy thiện cảm", "#06b6d4", 0.30, 1.05),
    ("Nữ Hào Hứng Nam 27 — Tường Vân (MC Talkshow Truyền Hình HTV)", "Thục Đoan", "Ngọc Trân", "tvc_south_news_htv", "MC Talkshow", "Duyên dáng, giàu cảm thán tự nhiên, dẫn dắt câu chuyện mượt mà", "#8b5cf6", 0.14, 1.02),
    ("Nữ Hào Hứng Nam 28 — Kim Chi (TVC Ẩm Thực & Nhà Hàng)", "Mỹ Duyên", "Thùy Dung", "tvc_south_emotive", "TVC F&B", "Ngọt ngào, kích thích vị giác, nhấn mạnh hương vị tuyệt hảo", "#f97316", 0.28, 1.05),
    ("Nữ Hào Hứng Nam 29 — Phương Anh (TVC Bảo Hiểm Nhân Thọ)", "Kim Thanh", "Thục Đoan", "tvc_south_corp", "TVC Bảo Hiểm", "Trìu mến, nhân văn, điểm rơi cuối câu chạm đến trái tim gia đình", "#0d9488", 0.04, 1.00),
    ("Nữ Hào Hứng Nam 30 — Diệu Nhi (KOC Review Đồ Gia Dụng Thông Minh)", "Thùy Dung", "Mỹ Duyên", "tvc_south_emotive", "Review SmartHome", "Linh hoạt, hào hứng, làm nổi bật sự tiện lợi vượt trội", "#f43f5e", 0.35, 1.06),
    ("Nữ Hào Hứng Nam 31 — Hoài An (Đọc Truyện Ngôn Tình Sôi Nổi)", "Mỹ Duyên", "Kim Thanh", "tvc_south_emotive", "Truyện Ngôn Tình", "Biểu cảm phong phú, thoại nhân vật sống động như phim", "#db2777", 0.18, 1.02),
    ("Nữ Hào Hứng Nam 32 — Khánh Ngọc (TVC Thẩm Mỹ Nụ Cười & Nha Khoa)", "Thùy Dung", "Thục Đoan", "tvc_south_pro_demo", "TVC Nha Khoa", "Tươi sáng, rạng ngời, truyền sự tự tin tỏa sáng ở cuối câu", "#0ea5e9", 0.25, 1.04),
    ("Nữ Hào Hứng Nam 33 — Mỹ Linh (TVC Sự Kiện Khai Trương Hồng Phát)", "Thùy Dung", "Mỹ Duyên", "tvc_south_emotive", "TVC Khai Trương", "Rộn ràng, náo nhiệt, khuấy động bầu không khí lễ hội", "#ef4444", 0.40, 1.07),
    ("Nữ Hào Hứng Nam 34 — Thanh Vy (Trợ Lý AI & Tổng Đài Thông Minh)", "Thục Đoan", "Ngọc Trân", "tvc_south_pro_demo", "Smart Assistant", "Thân thiện, nhiệt tình, ngữ điệu tự nhiên như nhân viên thật", "#10b981", 0.20, 1.03),
    ("Nữ Hào Hứng Nam 35 — Ngọc Tuyết (TVC Tết Phương Nam Sum Vầy)", "Mỹ Duyên", "Thục Đoan", "tvc_south_emotive", "TVC Tết Nam Bộ", "Ấm áp, rộn rã tiếng cười xuân, kết câu đong đầy hạnh phúc", "#dc2626", 0.22, 1.03),
]

NORTH_F_NAMES = [
    ("Nữ Hào Hứng Bắc 01 — Minh Hà (BTV Chuyển Động 24h)", "Mai Anh", "Đoan Trang", "tvc_north_news_phuong_linh", "BTV Năng Động VTV", "Sắc sảo, hiện đại, nhấn mạnh thông tin đắt giá ở khoản cuối", "#0284c7", 0.15, 1.05),
    ("Nữ Hào Hứng Bắc 02 — Quỳnh Nga (TVC Sale Sốc & Flash Sale)", "Đoan Trang", "Trúc Ly", "tvc_north_comfort", "TVC Flash Sale", "Hào hứng, dồn dập, thúc đẩy chốt đơn cực kỳ bùng nổ", "#e11d48", 0.40, 1.08),
    ("Nữ Hào Hứng Bắc 03 — Thu Trang (KOC Review Mỹ Phẩm Hà Nội)", "Trúc Ly", "Ngọc Huyền", "tvc_north_spa", "Beauty KOC", "Tự nhiên, cuốn hút, nhấn nhá ưu điểm sản phẩm như tâm sự thật", "#ec4899", 0.30, 1.06),
    ("Nữ Hào Hứng Bắc 04 — Hoàng Linh (MC Sự Kiện & Gameshow)", "Đoan Trang", "Mai Anh", "tvc_north_comfort", "MC Gameshow", "Năng lượng đỉnh cao, tươi vui, làm chủ hoàn toàn nhịp cảm xúc", "#f59e0b", 0.35, 1.07),
    ("Nữ Hào Hứng Bắc 05 — Phương Liên (TVC Bất Động Sản Vinhomes)", "Ngọc Linh", "Mai Anh", "tvc_north_warm_demo", "TVC BĐS Cao Cấp", "Sang trọng, tự hào, đẩy cao trào khẳng định vị thế ở cuối câu", "#d97706", 0.05, 1.02),
    ("Nữ Hào Hứng Bắc 06 — Ngọc Huyền Pro (Đọc Truyện Biểu Cảm Cao)", "Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)", "Ngọc Huyền", "tvc_north_warm_demo", "Truyện Ngôn Tình VIP", "Giọng mẫu gốc nâng cấp độ nảy cảm xúc và nhấn khoản cuối cực sâu", "#f97316", 0.08, 1.02),
    ("Nữ Hào Hứng Bắc 07 — Thanh Hằng (TVC Thời Trang Thượng Lưu)", "Trúc Ly", "Mai Anh", "tvc_north_spa", "TVC High Fashion", "Đẳng cấp, cuốn hút, nhịp đọc dứt khoát đầy thần thái", "#7c3aed", 0.12, 1.03),
    ("Nữ Hào Hứng Bắc 08 — Hương Giang (Livestream Chốt Đơn Nghìn Đơn)", "Đoan Trang", "Ngọc Huyền", "tvc_north_comfort", "Live Mega Sale", "Hoạt ngôn, lôi cuốn, nhấn mạnh giá sốc và quà tặng cuối câu", "#f43f5e", 0.42, 1.08),
    ("Nữ Hào Hứng Bắc 09 — Thùy Linh (MC Văn Hóa & Du Lịch VTV)", "Mai Anh", "Trúc Ly", "tvc_north_warm_demo", "MC Du Lịch VTV", "Trong sáng, truyền cảm hứng xê dịch, kết câu ngân vang đẹp đẽ", "#0891b2", 0.18, 1.03),
    ("Nữ Hào Hứng Bắc 10 — Bảo Anh (TVC Nước Giải Khát & GenZ)", "Trúc Ly", "Đoan Trang", "tvc_north_comfort", "TVC GenZ", "Trẻ trung, sảng khoái, tràn ngập tiếng cười và sức sống", "#06b6d4", 0.45, 1.07),
    ("Nữ Hào Hứng Bắc 11 — Nguyệt Ánh (TVC Ngân Hàng & Đầu Tư)", "Mai Anh", "Ngọc Linh", "tvc_north_news_phuong_linh", "TVC Tài Chính", "Đĩnh đạc, thuyết phục, nhấn mạnh lợi ích tài chính cuối câu", "#0d9488", 0.08, 1.03),
    ("Nữ Hào Hứng Bắc 12 — Diễm Quỳnh (MC Giao Lưu & Tọa Đàm)", "Ngọc Huyền", "Mai Anh", "tvc_north_warm_demo", "MC Tọa Đàm", "Gần gũi, thông tuệ, giàu cảm thán và nhịp lấy hơi người thật", "#2563eb", 0.10, 1.02),
    ("Nữ Hào Hứng Bắc 13 — Hải Yến (TVC Sữa & Chăm Sóc Bé Yêu)", "Ngọc Huyền", "Trúc Ly", "tvc_north_comfort", "TVC Mẹ & Bé", "Ngọt ngào, rạng rỡ niềm vui làm mẹ, ấm áp ở từng câu kết", "#10b981", 0.25, 1.04),
    ("Nữ Hào Hứng Bắc 14 — Trà My (Review Ẩm Thực & Quán Ngon Hà Nội)", "Đoan Trang", "Trúc Ly", "tvc_north_warm_demo", "Food Vlog Bắc", "Tự nhiên, hào hứng, miêu tả hương vị sống động như trước mắt", "#ea580c", 0.32, 1.06),
    ("Nữ Hào Hứng Bắc 15 — Lan Phương (Diễn Giả & Đào Tạo Doanh Nghiệp)", "Mai Anh", "Quỳnh Anh", "tvc_north_news_phuong_linh", "Corporate Trainer", "Truyền lửa, mạch lạc, nhấn mạnh từ khóa cốt lõi cực kỳ có lực", "#4f46e5", 0.12, 1.04),
    ("Nữ Hào Hứng Bắc 16 — Minh Trang (TVC Giáo Dục Quốc Tế)", "Đoan Trang", "Mai Anh", "tvc_north_warm_demo", "TVC Giáo Dục", "Hiện đại, chuẩn mực, khơi dậy ước mơ vươn tầm thế giới", "#0284c7", 0.20, 1.04),
    ("Nữ Hào Hứng Bắc 17 — Thúy Hạnh (TVC Thẩm Mỹ & Làm Đẹp)", "Trúc Ly", "Ngọc Linh", "tvc_north_spa", "TVC Beauty Clinic", "Mềm mại, quyến rũ, nâng niu cảm xúc người nghe đến chữ cuối cùng", "#db2777", 0.22, 1.02),
    ("Nữ Hào Hứng Bắc 18 — Kiều Anh (Đọc Truyện Đêm Khuya Sống Động)", "Quỳnh Anh", "Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)", "tvc_north_warm_demo", "Truyện Đêm Khuya", "Có tiếng thở dài, lấy hơi và nhấn nhá tâm lý nhân vật chân thực", "#9333ea", -0.05, 0.99),
    ("Nữ Hào Hứng Bắc 19 — Vân Trang (TVC Điện Máy & Gia Dụng)", "Đoan Trang", "Mai Anh", "tvc_north_comfort", "TVC Điện Máy", "Vang sáng, hào hứng, chốt thông điệp khuyến mãi cực kỳ bắt tai", "#ef4444", 0.34, 1.06),
    ("Nữ Hào Hứng Bắc 20 — Thu Thủy (BTV Bản Tin Kinh Tế Số)", "Mai Anh", "Đoan Trang", "tvc_north_news_phuong_linh", "BTV Kinh Tế", "Gãy gọn, thông minh, nhấn mạnh xu hướng và con số ấn tượng", "#0369a1", 0.16, 1.04),
    ("Nữ Hào Hứng Bắc 21 — Nhã Phương Bắc (TVC Dược Phẩm & Đông Y)", "Ngọc Huyền", "Ngọc Linh", "tvc_north_comfort", "TVC Dược Phẩm", "Ân cần, ấm áp, tạo sự an tâm tuyệt đối ở khoản cuối câu", "#059669", 0.06, 1.01),
    ("Nữ Hào Hứng Bắc 22 — Khánh Huyền (Podcast Chữa Lành & Cảm Hứng)", "Quỳnh Anh", "Trúc Ly", "tvc_north_spa", "Podcast Cảm Hứng", "Trong trẻo, truyền năng lượng yêu đời, nhẹ nhàng mà sâu sắc", "#8b5cf6", 0.14, 1.01),
    ("Nữ Hào Hứng Bắc 23 — Minh Hương (TVC Ô Tô & Công Nghệ Xanh)", "Mai Anh", "Trúc Ly", "tvc_north_news_phuong_linh", "TVC Auto & EV", "Hiện đại, bứt phá, nhấn mạnh công nghệ tương lai đầy kiêu hãnh", "#0284c7", 0.18, 1.05),
    ("Nữ Hào Hứng Bắc 24 — Hà Anh (KOC Thời Trang & Lifestyle)", "Trúc Ly", "Đoan Trang", "tvc_north_comfort", "Fashion KOC", "Sành điệu, tươi trẻ, nhịp nói lôi cuốn giới trẻ", "#ec4899", 0.36, 1.06),
    ("Nữ Hào Hứng Bắc 25 — Bích Hồng (TVC Tết Đoàn Viên Miền Bắc)", "Ngọc Linh", "Ngọc Huyền", "tvc_north_warm_demo", "TVC Tết Bắc", "Đầm ấm, rộn ràng sắc xuân Hà Nội, kết câu ngân dư âm sum vầy", "#dc2626", 0.10, 1.02),
    ("Nữ Hào Hứng Bắc 26 — Thảo Nguyên (Review Sách & Tinh Hoa Tri Thức)", "Quỳnh Anh", "Mai Anh", "tvc_north_warm_demo", "Book Review", "Truyền cảm, cuốn hút, nhấn mạnh những triết lý hay trong sách", "#0d9488", 0.05, 1.02),
    ("Nữ Hào Hứng Bắc 27 — Ánh Tuyết (TVC Trang Sức & Đá Quý)", "Trúc Ly", "Ngọc Huyền", "tvc_north_spa", "TVC Luxury Gems", "Tinh tế, sang quý, điểm rơi cuối câu tỏa sáng lấp lánh", "#ca8a04", 0.15, 1.01),
    ("Nữ Hào Hứng Bắc 28 — Mai Chi (MC Sự Kiện Khai Trương & Lễ Hội)", "Đoan Trang", "Trúc Ly", "tvc_north_comfort", "MC Khai Trương", "Hào hứng, náo nhiệt, khuấy động sự kiện ngay từ câu đầu tiên", "#f97316", 0.38, 1.07),
    ("Nữ Hào Hứng Bắc 29 — Ngọc Mai (TVC Hàng Không & Du Thuyền 5 Sao)", "Mai Anh", "Ngọc Huyền", "tvc_north_spa", "TVC 5-Star Travel", "Thanh lịch, ngọt ngào, chào đón quý khách bằng nụ cười trong giọng nói", "#0891b2", 0.14, 1.02),
    ("Nữ Hào Hứng Bắc 30 — Huyền Trang (TVC Thương Mại Điện Tử Siêu Sale)", "Đoan Trang", "Trúc Ly", "tvc_north_comfort", "Mega Campaign", "Tốc độ, bùng nổ, chốt hạ ưu đãi cuối câu không thể chối từ", "#e11d48", 0.44, 1.08),
    ("Nữ Hào Hứng Bắc 31 — Thanh Mai Pro (BTV Đặc Biệt & Phóng Sự Trọng Điểm)", "Mai Anh", "Ngọc Linh", "tvc_north_news_phuong_linh", "Phóng Sự VTV", "Uy lực, truyền cảm, nhấn mạnh kết luận phóng sự đầy sức nặng", "#1d4ed8", 0.05, 1.03),
    ("Nữ Hào Hứng Bắc 32 — Linh Chi (Vlogger Du Lịch & Trải Nghiệm)", "Trúc Ly", "Ngọc Huyền", "tvc_north_warm_demo", "Travel Vlog", "Hào hứng kể chuyện, có tiếng lấy hơi và cảm thán sống động", "#10b981", 0.28, 1.05),
    ("Nữ Hào Hứng Bắc 33 — Yến Vi (TVC Mỹ Phẩm Thiên Nhiên Organic)", "Ngọc Huyền", "Trúc Ly", "tvc_north_spa", "TVC Organic", "Trong lành, tươi mới, truyền cảm giác thư thái và tin yêu", "#16a34a", 0.22, 1.03),
    ("Nữ Hào Hứng Bắc 34 — Minh Tâm (Chuyên Gia Tư Vấn Tài Chính & BĐS)", "Mai Anh", "Quỳnh Anh", "tvc_north_warm_demo", "Tư Vấn VIP", "Chuyên nghiệp, nhiệt thành, nhấn mạnh cơ hội vàng ở khoản cuối", "#0f766e", 0.10, 1.03),
    ("Nữ Hào Hứng Bắc 35 — Hoàng Oanh (MC Truyền Hình & Gala Cuối Năm)", "Đoan Trang", "Mai Anh", "tvc_north_comfort", "MC Gala VTV", "Rực rỡ, xúc động, đẩy cảm xúc khán giả lên đỉnh điểm ở câu kết", "#d97706", 0.25, 1.05),
]

assert len(NEW_30_MALES) == 30, f"Expected 30 males, got {len(NEW_30_MALES)}"
assert len(SOUTH_F_NAMES) + len(NORTH_F_NAMES) == 70, f"Expected 70 females, got {len(SOUTH_F_NAMES) + len(NORTH_F_NAMES)}"

catalog_100_addition = []

# 1. Enroll 30 New Enthusiastic Male Voices
for idx, (vid, b1_n, b2_n, tvc_k, region, badge, style_desc, color, pst, spd) in enumerate(NEW_30_MALES, 1):
    b1 = tts._preset_voices[b1_n]
    b2 = tts._preset_voices[b2_n]
    alpha = 0.22 + ((idx * 17) % 55) / 100.0
    pairs = [(b1["speaker_emb"], 1.0 - alpha), (b2["speaker_emb"], alpha)]
    if tvc_k in harvested_embs:
        pairs.append((harvested_embs[tvc_k], 0.32))
    emb = blend_multi_emb(pairs, jitter_seed=1000 + idx)

    tts._preset_voices[vid] = {
        "description": f"Nam · {region} · {style_desc}",
        "gender": "male",
        "style": "tu_nhien",
        "featured": 50 + idx,
        "aliases": [],
        "speaker_emb": emb,
        "codes": b1["codes"].copy(),
    }
    # Map preview to rotating clean male studio previews (or dedicated preview)
    prev_pool = ["/previews/male_tvc_tuan_kiet.mp3", "/previews/male_tvc_minh_khoi.mp3", "/previews/male_tvc_hoang_quan.mp3"]
    prev_url = prev_pool[(idx - 1) % len(prev_pool)]
    short_name = vid.split("—")[-1].strip()
    catalog_100_addition.append({
        "id": vid,
        "name": short_name,
        "category": "male_tvc",
        "sub_group": "new_100_enthusiastic",
        "badge": badge.upper(),
        "region": region,
        "gender": "Nam",
        "style": f"{style_desc} · Nhấn mạnh ý hay & khoản cuối giàu tính con người",
        "avatar_color": color,
        "preview": prev_url,
        "pitch_st": pst,
        "speed_mul": spd,
        "enthusiastic": True,
    })

print("Enrolled 30 NEW Enthusiastic Male Voices.")

# 2. Enroll 35 New Enthusiastic Southern Female Voices
for idx, (vid, b1_n, b2_n, tvc_k, badge, style_desc, color, pst, spd) in enumerate(SOUTH_F_NAMES, 1):
    b1 = tts._preset_voices[b1_n]
    b2 = tts._preset_voices[b2_n]
    alpha = 0.20 + ((idx * 19) % 60) / 100.0
    pairs = [(b1["speaker_emb"], 1.0 - alpha), (b2["speaker_emb"], alpha)]
    if tvc_k in harvested_embs:
        pairs.append((harvested_embs[tvc_k], 0.28))
    emb = blend_multi_emb(pairs, jitter_seed=2000 + idx)

    tts._preset_voices[vid] = {
        "description": f"Nữ · Miền Nam · {style_desc}",
        "gender": "female",
        "style": "tu_nhien",
        "featured": 80 + idx,
        "aliases": [],
        "speaker_emb": emb,
        "codes": b1["codes"].copy(),
    }
    prev_idx = ((idx - 1) % 20) + 1
    prev_url = f"/previews/south_f_{prev_idx:02d}.mp3"
    short_name = vid.split("—")[-1].strip()
    catalog_100_addition.append({
        "id": vid,
        "name": short_name,
        "category": "female_south",
        "sub_group": "new_100_enthusiastic",
        "badge": badge.upper(),
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": f"{style_desc} · Nhấn mạnh ý hay & khoản cuối truyền cảm",
        "avatar_color": color,
        "preview": prev_url,
        "pitch_st": pst,
        "speed_mul": spd,
        "enthusiastic": True,
    })

print("Enrolled 35 NEW Enthusiastic Southern Female Voices.")

# 3. Enroll 35 New Enthusiastic Northern Female Voices
for idx, (vid, b1_n, b2_n, tvc_k, badge, style_desc, color, pst, spd) in enumerate(NORTH_F_NAMES, 1):
    b1 = tts._preset_voices[b1_n]
    b2 = tts._preset_voices[b2_n]
    alpha = 0.20 + ((idx * 23) % 60) / 100.0
    pairs = [(b1["speaker_emb"], 1.0 - alpha), (b2["speaker_emb"], alpha)]
    if tvc_k in harvested_embs:
        pairs.append((harvested_embs[tvc_k], 0.28))
    emb = blend_multi_emb(pairs, jitter_seed=3000 + idx)

    tts._preset_voices[vid] = {
        "description": f"Nữ · Miền Bắc · {style_desc}",
        "gender": "female",
        "style": "tu_nhien",
        "featured": 115 + idx,
        "aliases": [],
        "speaker_emb": emb,
        "codes": b1["codes"].copy(),
    }
    prev_idx = ((idx - 1) % 20) + 1
    prev_url = f"/previews/north_f_{prev_idx:02d}.mp3"
    short_name = vid.split("—")[-1].strip()
    catalog_100_addition.append({
        "id": vid,
        "name": short_name,
        "category": "female_north",
        "sub_group": "new_100_enthusiastic",
        "badge": badge.upper(),
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": f"{style_desc} · Nhấn mạnh ý hay & khoản cuối truyền cảm",
        "avatar_color": color,
        "preview": prev_url,
        "pitch_st": pst,
        "speed_mul": spd,
        "enthusiastic": True,
    })

print("Enrolled 35 NEW Enthusiastic Northern Female Voices.")

saved_p = tts.save_voices()
print("Saved all 144 studio voices to:", saved_p)
(REF_DIR / "voices_v3_turbo_enrolled.json").write_text(
    Path(saved_p).read_text(encoding="utf-8"), encoding="utf-8"
)
(BASE_DIR / "voices_100_addition.json").write_text(
    json.dumps(catalog_100_addition, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"Saved voices_100_addition.json with {len(catalog_100_addition)} new voices (30 Male + 70 Female).")
