import os
import re
import sys
import json
import time
import shutil
import hashlib
import urllib.parse
import urllib.request
import threading
import subprocess
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if sys.platform == "win32":
    if getattr(sys, "stdout", None) and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if getattr(sys, "stderr", None) and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

import numpy as np
import soundfile as sf
import imageio_ffmpeg

BASE_DIR = Path(__file__).resolve().parent
SITE_DIR = BASE_DIR / "netlify_site"
PREV_DIR = SITE_DIR / "previews"
REF_DIR = BASE_DIR / "voices_ref"
GEN_DIR = BASE_DIR / "generated_audio"
HISTORY_FILE = BASE_DIR / "history.json"
ACTIVE_TUNNEL_FILE = BASE_DIR / "active_vbee_tunnel.json"
OUTBOX_TUNNEL_FILE = Path(r"C:\Users\PC\Downloads\LGVelvetBridge\outbox\vbee_tunnel.json")
TUNNEL_LOG = BASE_DIR / "vbee_tunnel.log"
CLOUDFLARED_SRC = Path(r"C:\Users\PC\Downloads\LGVelvetBridge\cloudflared.exe")
TUNNEL_EXE = BASE_DIR / "vbee_tunnel.exe"
NTFY_TOPIC = "vbee_velvet_hieu_pc_8890"
PORT = int(os.environ.get("PORT", "8890"))
IS_CLOUD_COMPUTE = bool(os.environ.get("K_SERVICE") or os.environ.get("SPACE_ID") or os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("CLOUD_RUN_JOB"))
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

SITE_DIR.mkdir(parents=True, exist_ok=True)
PREV_DIR.mkdir(parents=True, exist_ok=True)
REF_DIR.mkdir(parents=True, exist_ok=True)
GEN_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def convert_to_pure_vietnamese(text: str) -> str:
    """Pure Vietnamese phonetic normalization while preserving all [emotion] and [breaktime] tags."""
    t = text.replace("\ufeff", "")
    # Protect inline bracket tags [breaktime=...], [hưng phấn], [nhấn mạnh], [lắng đọng], [tươi vui], [cười], [thở dài], [hắng giọng]
    protected = []

    def _save_tag(m):
        idx = len(protected)
        protected.append(m.group(0))
        return f"__VBEE_TAG_{idx}__"

    t = re.sub(r"\[[^\]]+\]", _save_tag, t)

    # Fix known Vbee artifact in user's story ("ca cần si" -> "bây giờ")
    t = re.sub(r"\bca\s+cần\s+si\b", "bây giờ?", t, flags=re.I)
    t = re.sub(r"\bTVC\s+3D\s+anamorphic\b", "phim quảng cáo ba đê nổi", t, flags=re.I)
    t = re.sub(r"\b3D\s+anamorphic\b", "ba đê nổi", t, flags=re.I)
    t = re.sub(r"\bTVC\s+3D\b", "phim quảng cáo ba đê", t, flags=re.I)
    t = re.sub(r"\bTVC\b", "ti vi xi", t, flags=re.I)
    t = re.sub(r"\b3D\b", "ba đê", t, flags=re.I)
    t = re.sub(r"\bKOL\b", "ây ô eo", t, flags=re.I)
    t = re.sub(r"\bKOC\b", "ây ô xi", t, flags=re.I)
    t = re.sub(r"\bMC\b", "em xi", t, flags=re.I)
    t = re.sub(r"\bVTV1\b", "vê tê vê một", t, flags=re.I)
    t = re.sub(r"\bVTV\b", "vê tê vê", t, flags=re.I)
    t = re.sub(r"\bHTV9\b", "hát tê vê chín", t, flags=re.I)
    t = re.sub(r"\bHTV7\b", "hát tê vê bảy", t, flags=re.I)
    t = re.sub(r"\bHTV\b", "hát tê vê", t, flags=re.I)
    t = re.sub(r"\bVIP\b", "víp", t, flags=re.I)
    t = re.sub(r"\bvest\b", "vét", t, flags=re.I)
    t = re.sub(r"\btip\b", "típ", t, flags=re.I)
    t = re.sub(r"\breview\b", "ri viu", t, flags=re.I)
    t = re.sub(r"\bpodcast\b", "pót cát", t, flags=re.I)
    t = re.sub(r"\bvlog\b", "vê lốc", t, flags=re.I)
    t = re.sub(r"\blivestream\b", "lai chim", t, flags=re.I)
    t = re.sub(r"\bsale\b", "sêu", t, flags=re.I)
    t = re.sub(r"\bvoucher\b", "vao chờ", t, flags=re.I)
    t = re.sub(r"\bdeal\b", "điu", t, flags=re.I)
    t = re.sub(r"\bhotline\b", "hót lai", t, flags=re.I)
    t = re.sub(r"\bspa\b", "sờ pa", t, flags=re.I)
    t = re.sub(r"\bVietinBank\b", "Việt Tin Băng", t, flags=re.I)
    t = re.sub(r"\bVietcombank\b", "Việt Com Băng", t, flags=re.I)
    t = re.sub(r"\bTechcombank\b", "Tếch Com Băng", t, flags=re.I)
    t = re.sub(r"\bVPBank\b", "Vi Pi Băng", t, flags=re.I)
    t = re.sub(r"\bMBBank\b", "Em Bi Băng", t, flags=re.I)
    t = re.sub(r"\bPremium\b", "Pờ ri mi um", t, flags=re.I)
    t = re.sub(r"\bLuxury\b", "Lắc xơ ri", t, flags=re.I)
    t = re.sub(r"\bVinhomes\b", "Vin Hôm", t, flags=re.I)
    t = re.sub(r"\bVinamilk\b", "Vi na miu", t, flags=re.I)
    t = re.sub(r"\bShopee\b", "Sóp pi", t, flags=re.I)
    t = re.sub(r"\bLazada\b", "La da đa", t, flags=re.I)
    t = re.sub(r"\bRahula\b", "Ra hu la", t, flags=re.I)
    t = re.sub(r"\bRadula\b", "Ra hu la", t, flags=re.I)
    # Tech, AI & Finance terms so Vietnamese voices never glitch on raw English IPA phonemes
    t = re.sub(r"\bAnthropic\b", "An thờ rô pích", t, flags=re.I)
    t = re.sub(r"\bPersonal\s+Finance\b", "Pơ sơ nồ Phai nen", t, flags=re.I)
    t = re.sub(r"\bPersonal\b", "Pơ sơ nồ", t, flags=re.I)
    t = re.sub(r"\bFinance\b", "Phai nen", t, flags=re.I)
    t = re.sub(r"\bClaude\b", "Cờ lốt", t, flags=re.I)
    t = re.sub(r"\bChatGPT\b", "Chát Gi Pi Ti", t, flags=re.I)
    t = re.sub(r"\bOpenAI\b", "Ô pần Ây Ai", t, flags=re.I)
    t = re.sub(r"\bGoogle\b", "Gu Gồ", t, flags=re.I)
    t = re.sub(r"\bYoutube\b", "Diu Túp", t, flags=re.I)
    t = re.sub(r"\bFacebook\b", "Phây Búc", t, flags=re.I)
    t = re.sub(r"\bTiktok\b", "Tíc Tóc", t, flags=re.I)
    t = re.sub(r"\bdatabase\b", "đây ta bây", t, flags=re.I)
    t = re.sub(r"\bapp\b", "áp", t, flags=re.I)
    t = re.sub(r"\bapps\b", "áp", t, flags=re.I)
    t = re.sub(r"\bAPI\b", "ây pi ai", t, flags=re.I)
    t = re.sub(r"\bCEO\b", "xi i ô", t, flags=re.I)
    t = re.sub(r"\bGDP\b", "gi đi pi", t, flags=re.I)
    t = re.sub(r"\bUSD\b", "đô la Mỹ", t, flags=re.I)
    t = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1 đến \2", t)
    # Normalize em-dash / en-dash into natural comma pause so G2P never stumbles
    t = re.sub(r"\s*[—–]\s*", ", ", t)

    for idx, val in enumerate(protected):
        t = t.replace(f"__VBEE_TAG_{idx}__", val)
    return t


SAD_KEYWORDS_RE = re.compile(
    r"(khóc|nước mắt|đau đớn|hối hận|thương xót|bùi ngùi|sợ hãi|nghèo|chết|quyên sinh|cô đơn|thở dài|xót xa|lạnh nhạt|xấu hổ|cay đắng|bi kịch|mất mát|chia ly|nghẹn ngào|tủi thân|viện phí|xoay sở|dơ bẩn|bịa đặt|hạn chế|nhắc lại từ đầu|khó khăn|mệt mỏi|lo lắng|áp lực|chật vật)",
    re.I,
)
HAPPY_KEYWORDS_RE = re.compile(
    r"(tươi vui|hạnh phúc|tuyệt vời|rạng rỡ|thành công|bùng nổ|khuyến mãi|ưu đãi|lễ hội|nụ cười|hân hoan|đón chào|đột phá|thịnh vượng|tinh hoa|yêu thương|chăm sóc|mừng rỡ|khu rừng đẹp|tuyệt mỹ|mở rộng|không cần phải nhớ|chỉ cần hỏi|phần còn lại giúp bạn|hỗ trợ bạn lâu dài|dễ dàng|thuận tiện)",
    re.I,
)
INSIGHT_KEYWORDS_RE = re.compile(
    r"(nhận định|nhìn rộng hơn|tóm lại|có thể thấy|lời dạy|bài học|đáng chú ý|điều quan trọng|thực chất|suy cho cùng|nói cách khác|bước đi này|thay vì|ngẫm lại|nhìn tổng thể|khẳng định)",
    re.I,
)


def detect_sentence_emotion(sent: str) -> str:
    """Detects 'sad', 'happy', 'insight', or 'neutral' from inline tags or Vietnamese lexical cues."""
    if re.search(r"\[(buồn|lắng đọng|thở dài|trầm buồn)\]", sent, flags=re.I):
        return "sad"
    if re.search(r"\[(vui|tươi vui|hưng phấn|sôi động|cười)\]", sent, flags=re.I):
        return "happy"
    if re.search(r"\[(nhận định|nhấn khoản cuối|nhấn ý hay)\]", sent, flags=re.I):
        if INSIGHT_KEYWORDS_RE.search(sent) or re.search(r"\[nhận định\]", sent, flags=re.I):
            return "insight"
    if INSIGHT_KEYWORDS_RE.search(sent):
        return "insight"
    if SAD_KEYWORDS_RE.search(sent):
        return "sad"
    if HAPPY_KEYWORDS_RE.search(sent):
        return "happy"
    return "neutral"


def generate_ai_nhan_dinh(raw_text: str) -> dict:
    """
    Analyzes the user's text and generates:
    1. A contextual 'Khoản Nhận Định' closing commentary sentence tailored to the topic.
    2. Emotional rhythm breakdown (counts of Vui, Buồn, Phân tích/Ý hay, Nhận định).
    """
    low = raw_text.lower()
    if any(k in low for k in ("anthropic", "claude", "personal finance", "database", "trí tuệ nhân tạo", "công nghệ", "tính năng", "dữ liệu", "phần mềm")):
        domain = "Công Nghệ & Tài Chính Số (AI / FinTech)"
        closing = "Nhận định chung: Bước đi này cho thấy công nghệ trí tuệ nhân tạo đang dần vượt qua vai trò công cụ đơn thuần để trở thành người cố vấn thực thụ, giúp con người tiết kiệm thời gian và ra quyết định thông minh hơn mỗi ngày."
        tone_advice = "Đọc mở đầu rõ ràng, mạch lạc (1.0x); nhấn sắc nét ở các tính năng và hạ nhịp sâu lắng, đĩnh đạc ở Khoản Nhận Định cuối bài."
    elif any(k in low for k in ("nhà vua", "hươu", "đức phật", "rahula", "lời dạy", "câu chuyện", "ăn trộm", "viện phí", "nước mắt", "khóc", "hồ biểu chánh")):
        domain = "Truyện Kể Nhân Văn & Triết Lý Đời Sống"
        closing = "Ngẫm lại mới thấy, giữa những biến thiên của cuộc đời, chính lòng trắc ẩn, sự tỉnh thức và tấm lòng chân thành mới là giá trị bền vững nhất giữ cho tâm hồn con người luôn bình yên."
        tone_advice = "Biến thiên nhịp điệu giàu cảm xúc: Lúc vui đọc sáng giọng (1.03x), lúc buồn hoặc hối hận hạ giọng chậm lại (0.93x, nghỉ 0.65s), và nhấn sâu ở câu đúc kết cuối."
    elif any(k in low for k in ("bất động sản", "nghỉ dưỡng", "thượng lưu", "tinh hoa", "ngân hàng", "di sản", "biet thu", "villa", "luxury", "premium")):
        domain = "TVC Thương Hiệu Cao Cấp & Bất Động Sản / Tài Chính"
        closing = "Có thể khẳng định, đây không chỉ là chuẩn mực sống xứng tầm đẳng cấp, mà còn là giá trị di sản thịnh vượng vững bền dành cho thế hệ tương lai."
        tone_advice = "Giọng đọc sang trọng, tròn vành rõ chữ; ngân nhẹ ở các tính từ đắt giá và nhấn uy lực ở điểm rơi thương hiệu cuối bài."
    else:
        domain = "Bình Luận Tổng Hợp & Điểm Tin Chuyên Sâu"
        closing = "Nhìn rộng hơn, đây chính là điểm nhấn quan trọng đòi hỏi sự chủ động nắm bắt cơ hội, từ đó tạo ra bước chuyển mình bền vững và hiệu quả nhất trong thực tế."
        tone_advice = "Nhịp đọc tự nhiên, liền mạch nguyên câu; phân tách rõ giữa câu dẫn nhập, câu liệt kê ý chính và câu nhận định kết bài."

    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+|\n+", raw_text) if s.strip()]
    counts = {"happy": 0, "sad": 0, "insight": 0, "neutral": 0}
    for s in sentences:
        emo = detect_sentence_emotion(s)
        counts[emo] = counts.get(emo, 0) + 1

    return {
        "domain": domain,
        "closing_nhan_dinh": closing,
        "tone_advice": tone_advice,
        "counts": counts,
        "total_sentences": len(sentences),
    }


def auto_ai_prosody_format(text: str, preset: str = "auto_human", include_nhan_dinh: bool = True) -> dict:
    """
    Bộ Luật Toán Học Giọng Người Thật (Human Prosody & Emotional Rhythm Constitution):
    1. Phân tích từng câu để gắn nhãn nhịp điệu thật: [vui] (nhịp tươi sáng), [buồn] (nhịp trầm lắng),
       [nhấn ý hay] (nhấn phân tích), và [nhận định] [nhấn khoản cuối] (điểm rơi đúc kết).
    2. Giữ liền mạch hơi thở nguyên câu (không cắt vụn bằng breaktime 0.20s sau dấu phẩy).
    3. Tự động tổng hợp thêm 'Khoản Nhận Định' ở cuối bài khi người dùng bấm AI Viết Lại (nếu bật include_nhan_dinh).
    """
    raw = re.sub(
        r"\s*\[(break(?:time)?\s*=\s*[0-9.]+s?|vui|buồn|nhận định|hưng phấn|sôi động|nhấn mạnh|nhấn ý hay|nhấn khoản cuối|cao trào|lắng đọng|trầm ấm|tươi vui|lấy hơi|hắng giọng|cười|thở dài|cảm thán)\]\s*",
        " ",
        text,
        flags=re.I,
    )
    raw = re.sub(r"(?:À này,\s*|Và đặc biệt nhé,\s*|Đáng chú ý nhất là,\s*|Thật sự ấn tượng,\s*)", "", raw, flags=re.I)
    # Strip previously appended AI Nhận định if re-running so it never duplicates
    raw = re.sub(r"\n*(?:Nhận định chung:|Ngẫm lại mới thấy,|Có thể khẳng định,|Nhìn rộng hơn, đây chính là điểm nhấn)[^\n]*$", "", raw.strip(), flags=re.I).strip()
    raw = re.sub(r"[ \t]+", " ", raw).strip()

    analysis = generate_ai_nhan_dinh(raw)
    if preset == "clean" or not raw:
        return {"formatted_text": raw, "analysis": analysis}

    cfg = {
        "auto_human": {"para_b": "0.55s", "default_tag": "[nhấn ý hay]"},
        "human_rewrite": {"para_b": "0.55s", "default_tag": "[nhấn ý hay]"},
        "tvc_energetic": {"para_b": "0.45s", "default_tag": "[vui]"},
        "tvc_luxury": {"para_b": "0.60s", "default_tag": "[lắng đọng]"},
        "news_vtv_htv": {"para_b": "0.50s", "default_tag": "[nhấn ý hay]"},
        "story_healing": {"para_b": "0.65s", "default_tag": "[buồn]"},
    }.get(preset, {"para_b": "0.55s", "default_tag": "[nhấn ý hay]"})

    paragraphs = [p.strip() for p in re.split(r"\n+", raw) if p.strip()]
    formatted_paras = []
    for p_idx, para in enumerate(paragraphs):
        sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", para) if s.strip()]
        tagged_sents = []
        for s_idx, s in enumerate(sents):
            s_clean = re.sub(r"\s*,\s*", ", ", s)
            s_clean = re.sub(r"\s*;\s*", "; ", s_clean)
            s_clean = re.sub(r"\s*:\s*", ": ", s_clean)
            emo = detect_sentence_emotion(s_clean)
            if emo == "sad":
                tag = "[buồn]"
            elif emo == "happy":
                tag = "[vui]"
            elif emo == "insight":
                tag = "[nhận định] [nhấn khoản cuối]"
            else:
                if s_idx == len(sents) - 1 and p_idx == len(paragraphs) - 1 and not include_nhan_dinh:
                    tag = "[nhận định] [nhấn khoản cuối]"
                elif ":" in s_clean or s_idx == 0:
                    tag = cfg["default_tag"]
                else:
                    tag = ""
            tagged_sents.append(f"{tag} {s_clean}".strip())
        formatted_paras.append(" ".join(tagged_sents))

    if include_nhan_dinh and analysis.get("closing_nhan_dinh"):
        formatted_paras.append(f"[nhận định] [nhấn khoản cuối] {analysis['closing_nhan_dinh']}")
        analysis["counts"]["insight"] = analysis["counts"].get("insight", 0) + 1

    out_text = f"\n[breaktime={cfg['para_b']}]\n".join(formatted_paras)
    return {"formatted_text": out_text, "analysis": analysis}


# ── 44 COPYRIGHT-SAFE STUDIO VOICES CATALOG ─────────────────────────────────
# 1 Giọng Mẫu Gốc + 40 Giọng Nữ (20 Bắc VTV1/TVC + 20 Nam HTV/TVC) + 3 Giọng Nam TVC/Truyền Hình
VOICE_CATALOG = [
    {
        "id": "Lê Tuệ Nghi — Giọng Nữ Truyện Mẫu Gốc (Miền Bắc)",
        "enrolled_key": "Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)",
        "name": "Lê Tuệ Nghi (Truyện Ngôn Tình Mẫu Gốc)",
        "category": "vbee_original",
        "use_case": "podcast",
        "badge": "GIỌNG MẪU GỐC",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "Đọc truyện ngôn tình & tâm sự · Truyền cảm chuẩn 1:1 file mẫu gốc",
        "avatar_color": "#FF2A85",
        "preview": "/previews/vbee_ngoc_huyen_goc.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Nguyễn Hà Khuê — Nữ Bản Tin Thời Sự Bắc",
        "enrolled_key": "Nữ VTV1 & TVC Bắc 01 — Thanh Mai",
        "name": "Nguyễn Hà Khuê (Bản Tin Thời Sự Bắc)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "BẢN TIN MIỀN BẮC",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "Phát thanh viên Thời sự Hà Nội · Đĩnh đạc, tròn vành rõ chữ, uy tín",
        "avatar_color": "#00D2FF",
        "preview": "/previews/north_f_01.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Phạm Minh Uyên — Nữ TVC Bất Động Sản Bắc",
        "enrolled_key": "Nữ TVC Bắc 02 — Phương Thảo",
        "name": "Phạm Minh Uyên (TVC Bất Động Sản Luxury)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TVC BẤT ĐỘNG SẢN",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Bất động sản & Nghỉ dưỡng cao cấp · Sang trọng, sâu lắng, đẳng cấp",
        "avatar_color": "#F59E0B",
        "preview": "/previews/north_f_02.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Đỗ Tuệ Lâm — Nữ TVC Tài Chính Ngân Hàng Bắc",
        "enrolled_key": "Nữ TVC Bắc 03 — Minh Châu",
        "name": "Đỗ Tuệ Lâm (TVC Tài Chính & Ngân Hàng)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TVC TÀI CHÍNH",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Ngân hàng số & Bảo hiểm · Tin cậy, ấm áp, thuyết phục",
        "avatar_color": "#14B8A6",
        "preview": "/previews/north_f_03.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Bùi Nhã Đan — Nữ TVC Dược Phẩm Bắc",
        "enrolled_key": "Nữ TVC Bắc 04 — Lan Hương",
        "name": "Bùi Nhã Đan (TVC Sức Khỏe & Dược Phẩm)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TVC SỨC KHỎE",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Dược phẩm & Chăm sóc sức khỏe · Ân cần, rõ ràng, chuẩn chuyên gia",
        "avatar_color": "#10B981",
        "preview": "/previews/north_f_04.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Vũ Thanh Trúc — Nữ TVC Mỹ Phẩm Bắc",
        "enrolled_key": "Nữ TVC Bắc 05 — Thu Hà",
        "name": "Vũ Thanh Trúc (TVC Mỹ Phẩm & Skincare)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TVC SKINCARE",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Mỹ phẩm & Làm đẹp Gen Z · Trong trẻo, mềm mại, cuốn hút",
        "avatar_color": "#EC4899",
        "preview": "/previews/north_f_05.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Hoàng Bảo Vy — Nữ TVC Siêu Sale Bắc",
        "enrolled_key": "Nữ TVC Bắc 06 — Khánh Linh",
        "name": "Hoàng Bảo Vy (TVC Siêu Sale & TikTok Shop)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TIKTOK SHOP SALE",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Khuyến mãi & TikTok Shop · Tươi trẻ, năng lượng, bắt tai",
        "avatar_color": "#FF2A85",
        "preview": "/previews/north_f_06.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Trần Ngọc Diệp — Nữ Điểm Tin Kinh Tế Bắc",
        "enrolled_key": "Nữ VTV1 Bắc 07 — Bích Ngọc",
        "name": "Trần Ngọc Diệp (Điểm Tin Kinh Tế Bắc)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "ĐIỂM TIN KINH TẾ",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "Bản tin Tài chính & Xu hướng thị trường · Sắc sảo, hiện đại, gãy gọn",
        "avatar_color": "#3B82F6",
        "preview": "/previews/north_f_07.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Đặng Phương Liên — Nữ TVC Gia Đình Bắc",
        "enrolled_key": "Nữ TVC Bắc 08 — Quỳnh Hoa",
        "name": "Đặng Phương Liên (TVC Gia Đình & Ẩm Thực)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TVC GIA ĐÌNH",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Gia đình & Thực phẩm dinh dưỡng · Đằm thắm, dịu dàng, ấm cúng",
        "avatar_color": "#F97316",
        "preview": "/previews/north_f_08.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Ngô Hoài An — Nữ Truyện Đêm Khuya Bắc",
        "enrolled_key": "Nữ Truyện Bắc 09 — Hồng Nhung",
        "name": "Ngô Hoài An (Đọc Truyện Đêm Khuya Hà Nội)",
        "category": "female_north",
        "use_case": "podcast",
        "badge": "TRUYỆN ĐÊM KHUYA",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "Đọc truyện đêm khuya & Tản văn Hà Nội · Truyền cảm, lắng đọng, chạm cảm xúc",
        "avatar_color": "#A855F7",
        "preview": "/previews/north_f_09.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Lương Thảo Chi — Nữ TVC Giáo Dục Bắc",
        "enrolled_key": "Nữ TVC Bắc 10 — Thùy Dương",
        "name": "Lương Thảo Chi (TVC Giáo Dục & E-Learning)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "EDTECH & KHÓA HỌC",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Giáo dục & Học viện Quốc tế · Thân thiện, truyền cảm hứng học tập",
        "avatar_color": "#06B6D4",
        "preview": "/previews/north_f_10.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Đinh Khánh Hà — Nữ TVC Du Lịch Bắc",
        "enrolled_key": "Nữ TVC Bắc 11 — Bảo Quyên",
        "name": "Đinh Khánh Hà (TVC Hàng Không & Du Lịch)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TVC TRAVEL",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Hàng không & Du lịch trải nghiệm · Thanh lịch, nhẹ nhàng, sang trọng",
        "avatar_color": "#0EA5E9",
        "preview": "/previews/north_f_11.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Trương Ánh Dương — Nữ Review Công Nghệ Bắc",
        "enrolled_key": "Nữ TVC Bắc 12 — Diệu Linh",
        "name": "Trương Ánh Dương (Review Đồ Công Nghệ & Unbox)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "UNBOX & REVIEW",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "Review sản phẩm TikTok/Reels & Quảng cáo số · Tự nhiên, cuốn hút, nhịp trẻ",
        "avatar_color": "#F43F5E",
        "preview": "/previews/north_f_12.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Phan Minh Nguyệt — Nữ Sách Nói Bắc",
        "enrolled_key": "Nữ Audiobook Bắc 13 — Mai Phương",
        "name": "Phan Minh Nguyệt (Sách Nói & Kỹ Năng Sống)",
        "category": "female_north",
        "use_case": "podcast",
        "badge": "AUDIOBOOK BẮC",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "Sách nói Audiobook & Kỹ năng sống · Trầm ấm, thông thái, nghe lâu không mỏi",
        "avatar_color": "#6366F1",
        "preview": "/previews/north_f_13.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Mai Bảo Hân — Nữ TVC Thời Trang Bắc",
        "enrolled_key": "Nữ TVC Bắc 14 — Hà My",
        "name": "Mai Bảo Hân (TVC Thời Trang Gen Z)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "FASHION GEN Z",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Thời trang & Lookbook giới trẻ · Trẻ trung, sành điệu, giàu sức sống",
        "avatar_color": "#EC4899",
        "preview": "/previews/north_f_14.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Cao Tường Vân — Nữ Ký Sự Văn Hóa Bắc",
        "enrolled_key": "Nữ VTV1 Bắc 15 — Tuyết Ngân",
        "name": "Cao Tường Vân (Ký Sự & Phim Tài Liệu)",
        "category": "female_north",
        "use_case": "podcast",
        "badge": "KÝ SỰ & TÀI LIỆU",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "Phim tài liệu & Ký sự văn hóa · Sâu sắc, truyền cảm, giàu chất văn học",
        "avatar_color": "#3B82F6",
        "preview": "/previews/north_f_15.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Dương Tâm Đan — Nữ Podcast Chữa Lành Bắc",
        "enrolled_key": "Nữ Podcast Bắc 16 — Thanh Tâm",
        "name": "Dương Tâm Đan (Podcast Chữa Lành Đêm Khuya)",
        "category": "female_north",
        "use_case": "podcast",
        "badge": "PODCAST HEALING",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "Podcast Chữa lành & Tâm sự Gen Z · Nhẹ nhàng, thủ thỉ, xoa dịu tâm hồn",
        "avatar_color": "#8B5CF6",
        "preview": "/previews/north_f_16.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Tạ Quỳnh Anh — Nữ TVC Mẹ & Bé Bắc",
        "enrolled_key": "Nữ TVC Bắc 17 — Ngọc Ánh",
        "name": "Tạ Quỳnh Anh (TVC Mẹ & Bé)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TVC MẸ & BÉ",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Mẹ & Bé / Sữa dinh dưỡng · Ngọt ngào, trìu mến, giàu tình yêu thương",
        "avatar_color": "#F59E0B",
        "preview": "/previews/north_f_17.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Chu Lam Phương — Nữ TVC Công Nghệ Bắc",
        "enrolled_key": "Nữ TVC Bắc 18 — Hoài Thương",
        "name": "Chu Lam Phương (TVC Ô Tô & Công Nghệ Số)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TVC TECH",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Ô tô & Công nghệ tương lai · Hiện đại, dứt khoát, đẳng cấp",
        "avatar_color": "#00D2FF",
        "preview": "/previews/north_f_18.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Nghiêm Xuân Hiền — Nữ TVC Tết Đoàn Viên Bắc",
        "enrolled_key": "Nữ TVC Bắc 19 — Kim Oanh",
        "name": "Nghiêm Xuân Hiền (TVC Tết Đoàn Viên Bắc Bộ)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "TVC TẾT BẮC",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "TVC Tết & Sum vầy đoàn viên · Xúc động, ấm áp, gợi nhớ quê hương",
        "avatar_color": "#EF4444",
        "preview": "/previews/north_f_19.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Lại Thục Quyên — Nữ Trợ Lý AI & Hotline Bắc",
        "enrolled_key": "Nữ TVC Bắc 20 — Vân Anh",
        "name": "Lại Thục Quyên (Trợ Lý AI & Hotline Thương Hiệu)",
        "category": "female_north",
        "use_case": "tvc",
        "badge": "AI ASSISTANT",
        "region": "Miền Bắc",
        "gender": "Nữ",
        "style": "Tổng đài AI & Trợ lý thương hiệu · Chuẩn mực, lễ phép, thân thiện 24/7",
        "avatar_color": "#10B981",
        "preview": "/previews/north_f_20.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Huỳnh Gia Mẫn — Nữ Bản Tin Thời Sự Sài Gòn",
        "enrolled_key": "Nữ HTV & TVC Nam 01 — Thùy Trang",
        "name": "Huỳnh Gia Mẫn (Bản Tin Thời Sự Sài Gòn)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "BẢN TIN SÀI GÒN",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "Phát thanh viên Thời sự Sài Gòn · Ngọt ngào, chuẩn mực, hiền hòa",
        "avatar_color": "#FF2A85",
        "preview": "/previews/south_f_01.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Lâm Khả Hân — Nữ MC Giải Trí Nam Bộ",
        "enrolled_key": "Nữ HTV Nam 02 — Ngọc Hân",
        "name": "Lâm Khả Hân (MC Giải Trí & Sự Kiện Sài Gòn)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "MC SỰ KIỆN NAM",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "MC Giải trí & Văn nghệ Sài Gòn · Duyên dáng, gần gũi, giàu cảm xúc",
        "avatar_color": "#F43F5E",
        "preview": "/previews/south_f_02.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Võ Thảo Đan — Nữ TVC Gia Đình Nam Bộ",
        "enrolled_key": "Nữ TVC Nam 03 — Mỹ Tiên",
        "name": "Võ Thảo Đan (TVC Gia Đình & Ẩm Thực Nam Bộ)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC GIA ĐÌNH NAM",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Gia đình & Ẩm thực phương Nam · Ấm áp, tươi vui, đậm tình miền Nam",
        "avatar_color": "#F97316",
        "preview": "/previews/south_f_03.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Châu Yến Nhi — Nữ TVC Spa Sài Gòn",
        "enrolled_key": "Nữ TVC Nam 04 — Phương Trinh",
        "name": "Châu Yến Nhi (TVC Spa & Làm Đẹp Sài Gòn)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC SPA & BEAUTY",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Thẩm mỹ viện & Spa Sài Gòn · Mượt mà, sang trọng, êm dịu cuốn hút",
        "avatar_color": "#EC4899",
        "preview": "/previews/south_f_04.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Phan Bảo Ngọc — Nữ TVC Siêu Thị Sài Gòn",
        "enrolled_key": "Nữ TVC Nam 05 — Khánh Ngân",
        "name": "Phan Bảo Ngọc (TVC Siêu Thị & Mega Sale)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "MEGA SALE NAM",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Siêu thị & Khuyến mãi sôi động · Hào hứng, tiết tấu nhanh, bắt tai",
        "avatar_color": "#EF4444",
        "preview": "/previews/south_f_05.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Đoàn Nhã Khanh — Nữ TVC Đô Thị Sinh Thái Nam",
        "enrolled_key": "Nữ TVC Nam 06 — Bảo Trân",
        "name": "Đoàn Nhã Khanh (TVC Đô Thị Sinh Thái Nam Bộ)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC BĐS NAM BỘ",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Bất động sản & Đô thị sinh thái · Tinh tế, thanh thoát, truyền cảm hứng",
        "avatar_color": "#F59E0B",
        "preview": "/previews/south_f_06.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Lê Quế Trân — Nữ Ký Sự Miền Tây",
        "enrolled_key": "Nữ HTV Nam 07 — Thanh Thảo",
        "name": "Lê Quế Trân (Ký Sự Miền Tây Sông Nước)",
        "category": "female_south",
        "use_case": "podcast",
        "badge": "KÝ SỰ MIỀN TÂY",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "MC Ký sự miền Tây & Du lịch sinh thái · Mộc mạc, chân thành, ngọt ngào",
        "avatar_color": "#10B981",
        "preview": "/previews/south_f_07.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Trần Thiên Di — Nữ TVC Dinh Dưỡng Cho Bé",
        "enrolled_key": "Nữ TVC Nam 08 — Nhã Phương",
        "name": "Trần Thiên Di (TVC Sữa & Dinh Dưỡng Cho Bé)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC DINH DƯỠNG",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Sữa & Dinh dưỡng trẻ em · Trong trẻo, âu yếm, tràn đầy năng lượng",
        "avatar_color": "#FBBF24",
        "preview": "/previews/south_f_08.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Diệp Tường Khuê — Nữ Podcast Tâm Sự Sài Gòn",
        "enrolled_key": "Nữ Podcast Nam 09 — Tường Vy",
        "name": "Diệp Tường Khuê (Podcast Tâm Sự Sài Gòn Đêm)",
        "category": "female_south",
        "use_case": "podcast",
        "badge": "PODCAST SÀI GÒN",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "Podcast Tâm sự tình yêu & Chữa lành · Sâu lắng, thơ mộng, thủ thỉ đêm khuya",
        "avatar_color": "#A855F7",
        "preview": "/previews/south_f_09.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Mã Tuyết Nhi — Nữ TVC Ngân Hàng Số Sài Gòn",
        "enrolled_key": "Nữ TVC Nam 10 — Minh Thư",
        "name": "Mã Tuyết Nhi (TVC Ví Điện Tử & Ngân Hàng Số)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC FINTECH",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Ngân hàng số & Ví điện tử Gen Z · Hiện đại, thông minh, nhịp trẻ trung",
        "avatar_color": "#00D2FF",
        "preview": "/previews/south_f_10.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Hồ Đoan Trang — Nữ TVC Thảo Dược Nam Bộ",
        "enrolled_key": "Nữ TVC Nam 11 — Hoàng Yến",
        "name": "Hồ Thảo Nguyên (TVC Thảo Dược & Sức Khỏe)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC THẢO DƯỢC",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Dược phẩm & Thảo dược thiên nhiên · Điềm đạm, tin cậy, nhẹ nhàng",
        "avatar_color": "#14B8A6",
        "preview": "/previews/south_f_11.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Tô Mộc Lan — Nữ Đọc Truyện Miền Nam",
        "enrolled_key": "Nữ Truyện Nam 12 — Cẩm Ly",
        "name": "Tô Mộc Lan (Đọc Truyện Ngôn Tình Miền Nam)",
        "category": "female_south",
        "use_case": "podcast",
        "badge": "TRUYỆN MIỀN NAM",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "Đọc truyện ngôn tình & Tiểu thuyết miền Nam · Ngọt ngào, sâu lắng, truyền cảm",
        "avatar_color": "#9333EA",
        "preview": "/previews/south_f_12.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Khưu Mỹ Kỳ — Nữ TVC Mỹ Phẩm Sài Gòn",
        "enrolled_key": "Nữ TVC Nam 13 — Diễm My",
        "name": "Khưu Mỹ Kỳ (TVC Mỹ Phẩm & Lookbook Gen Z)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC COSMETICS",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Mỹ phẩm & Chăm sóc da · Trẻ trung, sang chảnh, cuốn hút tự nhiên",
        "avatar_color": "#EC4899",
        "preview": "/previews/south_f_13.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Lữ Băng Tâm — Nữ TVC Nước Giải Khát",
        "enrolled_key": "Nữ TVC Nam 14 — Trúc Đào",
        "name": "Lữ Băng Tâm (TVC Nước Giải Khát Mùa Hè)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC SẢNG KHOÁI",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Trà trái cây & Giải khát mùa hè · Sôi nổi, tươi mát, bùng nổ",
        "avatar_color": "#06B6D4",
        "preview": "/previews/south_f_14.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Bạch Kim Tuyền — Nữ Bản Tin Tiêu Dùng Nam",
        "enrolled_key": "Nữ HTV Nam 15 — Kim Ngân",
        "name": "Bạch Kim Tuyền (Bản Tin Tiêu Dùng & Kinh Tế)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TIN TIÊU DÙNG",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "Bản tin Kinh tế & Tiêu dùng thông minh · Rõ ràng, mạch lạc, chuyên nghiệp",
        "avatar_color": "#3B82F6",
        "preview": "/previews/south_f_15.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Từ Khả Ái — Nữ Review Ẩm Thực Sài Gòn",
        "enrolled_key": "Nữ Review Nam 16 — Ái Nhi",
        "name": "Từ Khả Ái (Review Ẩm Thực & Cafe Sài Gòn)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "FOOD TOUR SÀI GÒN",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "Review Quán xá, Trà sữa & Du lịch Sài Gòn · Tự nhiên, hào hứng, cuốn hút",
        "avatar_color": "#F97316",
        "preview": "/previews/south_f_16.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Nhan Tịnh Yên — Nữ Sách Nói Chữa Lành Nam",
        "enrolled_key": "Nữ Sách Nói Nam 17 — Huệ Mẫn",
        "name": "Nhan Tịnh Yên (Sách Nói Tâm Linh & Thiền Định)",
        "category": "female_south",
        "use_case": "podcast",
        "badge": "AUDIOBOOK HEALING",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "Sách nói & Thiền chữa lành miền Nam · Từ hòa, an nhiên, tĩnh tại",
        "avatar_color": "#6366F1",
        "preview": "/previews/south_f_17.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Âu Xuân Thảo — Nữ TVC Tết Phương Nam",
        "enrolled_key": "Nữ TVC Nam 18 — Quỳnh Như",
        "name": "Âu Xuân Thảo (TVC Tết Phương Nam Sum Vầy)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC TẾT NAM BỘ",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Tết đoàn viên & Quà tặng phương Nam · Đầm ấm, rộn ràng, chan chứa yêu thương",
        "avatar_color": "#EF4444",
        "preview": "/previews/south_f_18.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Kiều Minh Thư — Nữ TVC Trang Sức Sài Gòn",
        "enrolled_key": "Nữ TVC Nam 19 — Thiên Kim",
        "name": "Kiều Minh Thư (TVC Trang Sức & Phụ Kiện Cao Cấp)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "TVC LUXURY",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "TVC Trang sức & Thời trang cao cấp · Quý phái, kiêu sa, nhấn nhá tinh tế",
        "avatar_color": "#FBBF24",
        "preview": "/previews/south_f_19.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Thạch Uyển Nhi — Nữ CSKH Thương Hiệu Nam",
        "enrolled_key": "Nữ TVC Nam 20 — Ngọc Bích",
        "name": "Thạch Uyển Nhi (CSKH & Tổng Đài Miền Nam)",
        "category": "female_south",
        "use_case": "tvc",
        "badge": "CSKH MIỀN NAM",
        "region": "Miền Nam",
        "gender": "Nữ",
        "style": "Chăm sóc khách hàng & Hotline thương hiệu · Dịu dàng, lịch sự, thiện cảm",
        "avatar_color": "#10B981",
        "preview": "/previews/south_f_20.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Lâm Gia Khiêm — Nam TVC & Đời Sống Sài Gòn",
        "enrolled_key": "Nam TVC Miền Nam — Minh Khôi",
        "name": "Lâm Gia Khiêm (Nam TVC & Đời Sống Sài Gòn)",
        "category": "male_tvc",
        "use_case": "tvc",
        "badge": "NAM TVC MIỀN NAM",
        "region": "Miền Nam",
        "gender": "Nam",
        "style": "Trầm ấm · Đời thường · Chuẩn TVC Gia đình, Bảo hiểm & Phóng sự miền Nam",
        "avatar_color": "#10B981",
        "preview": "/previews/male_tvc_minh_khoi.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Đỗ Trọng Khang — Nam TVC & Thuyết Minh Hà Nội",
        "enrolled_key": "Nam TVC Miền Bắc — Hoàng Quân",
        "name": "Đỗ Trọng Khang (Nam TVC & Thuyết Minh Hà Nội)",
        "category": "male_tvc",
        "use_case": "tvc",
        "badge": "NAM TVC MIỀN BẮC",
        "region": "Miền Bắc",
        "gender": "Nam",
        "style": "Lịch lãm · Hào sảng · Thuyết minh truyền hình, TVC Ô tô, Ngân hàng & BĐS",
        "avatar_color": "#00D2FF",
        "preview": "/previews/male_tvc_hoang_quan.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    },
    {
        "id": "Trần Nhật Hào — Nam TVC Sôi Động & Livestream",
        "enrolled_key": "Nam TVC Sôi Động — Tuấn Kiệt",
        "name": "Trần Nhật Hào (Nam TVC Sôi Động & Livestream)",
        "category": "male_tvc",
        "use_case": "tvc",
        "badge": "NAM TVC SÔI ĐỘNG",
        "region": "Miền Nam",
        "gender": "Nam",
        "style": "Năng lượng · Nhấn nhá truyền lửa · TVC Khuyến mãi, Sự kiện & TikTok Creator",
        "avatar_color": "#F59E0B",
        "preview": "/previews/male_tvc_tuan_kiet.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0
    }
]

# Load the 100 Additional Enthusiastic Voices (30 Male + 70 Female -> 144 Voices)
ADDITION_100_FILE = BASE_DIR / "voices_100_addition.json"
if ADDITION_100_FILE.exists():
    try:
        extra_100 = json.loads(ADDITION_100_FILE.read_text(encoding="utf-8"))
        existing_ids = {v["id"] for v in VOICE_CATALOG}
        for ev in extra_100:
            if ev["id"] not in existing_ids:
                VOICE_CATALOG.append(ev)
                existing_ids.add(ev["id"])
    except Exception as _e:
        print(f"Warn loading voices_100_addition.json: {_e}")

# Load the 500 TVC Quảng Cáo & Podcast Corpus (VietinBank Premium + 12XHCjcngz4 + 500 TVC/Podcast Voices)
TVC_500_FILE = BASE_DIR / "voices_500_tvc.json"
if TVC_500_FILE.exists():
    try:
        extra_500 = json.loads(TVC_500_FILE.read_text(encoding="utf-8"))
        existing_ids = {v["id"] for v in VOICE_CATALOG}
        # Put the 2 flagship voices (VietinBank Premium & Nghệ Sĩ Trầm Hương 12XHCjcngz4) right near the top!
        for idx_500, ev in enumerate(extra_500):
            if ev["id"] not in existing_ids:
                if idx_500 < 4:
                    VOICE_CATALOG.insert(1 + idx_500, ev)
                else:
                    VOICE_CATALOG.append(ev)
                existing_ids.add(ev["id"])
    except Exception as _e5:
        print(f"Warn loading voices_500_tvc.json: {_e5}")

# Also load any user-cloned voices from voices_v3_turbo_enrolled.json that have clone_*.mp3 previews
try:
    _enrolled_p = REF_DIR / "voices_v3_turbo_enrolled.json"
    if _enrolled_p.exists():
        _edata = json.loads(_enrolled_p.read_text(encoding="utf-8")).get("presets", {})
        _existing_ids = {v["id"] for v in VOICE_CATALOG} | {v.get("enrolled_key") for v in VOICE_CATALOG if v.get("enrolled_key")}
        for _vname, _vinfo in _edata.items():
            if _vname in _existing_ids:
                continue
            _slug = re.sub(r"[^a-zA-Z0-9]+", "_", _vname.lower()).strip("_")
            _prev_p = PREV_DIR / f"clone_{_slug}.mp3"
            if _prev_p.exists():
                _is_female = str(_vinfo.get("gender", "")).lower() == "female"
                _desc = str(_vinfo.get("description", ""))
                _reg = "Miền Bắc" if "Bắc" in _desc else "Miền Nam"
                VOICE_CATALOG.insert(min(3, len(VOICE_CATALOG)), {
                    "id": _vname,
                    "name": _vname,
                    "category": "female_south" if (_is_female and "Nam" in _reg) else ("female_north" if _is_female else "male_tvc"),
                    "use_case": "podcast" if any(k in _desc.lower() for k in ("podcast", "truyện", "kể chuyện", "sách")) else "tvc",
                    "badge": "AI CLONED",
                    "region": _reg,
                    "gender": "Nữ" if _is_female else "Nam",
                    "style": _desc or "Giọng đọc TVC truyền cảm vừa học tự động",
                    "avatar_color": "#ec4899" if _is_female else "#0ea5e9",
                    "preview": f"/previews/clone_{_slug}.mp3",
                    "pitch_st": 0.0,
                    "speed_mul": 1.0,
                })
                _existing_ids.add(_vname)
except Exception as _ce:
    print(f"Warn loading custom cloned voices: {_ce}")

# Ensure EVERY voice in VOICE_CATALOG has use_case ('tvc' or 'podcast') & zero formant-warping defaults
PODCAST_KEYWORDS_RE = re.compile(
    r"(podcast|truyện|sách nói|audiobook|đêm khuya|tâm sự|chữa lành|radio|tản văn|hồ biểu chánh|ngôn tình|kể chuyện|story)",
    re.I,
)
for _v in VOICE_CATALOG:
    if not _v.get("use_case"):
        _hay = f"{_v.get('id', '')} {_v.get('name', '')} {_v.get('badge', '')} {_v.get('style', '')}"
        _v["use_case"] = "podcast" if PODCAST_KEYWORDS_RE.search(_hay) else "tvc"
    # Law 4: Zero-Vocoder Formant Invariance (prevent asetrate/atempo metallic robot artifacts at 1.0x)
    _v["pitch_st"] = 0.0
    _v["speed_mul"] = 1.0

VOICE_META_MAP = {v["id"]: v for v in VOICE_CATALOG}

# Backward-compatible aliases so any legacy request still resolves cleanly
LEGACY_VOICE_ALIASES = {
    "MC Quyền Linh (Truyền Cảm Đời Thường)": "Nam TVC Miền Nam — Minh Khôi",
    "MC Thanh Bạch (Sôi Động Sân Khấu)": "Nam TVC Sôi Động — Tuấn Kiệt",
    "MC Nguyễn Ngọc Ngạn (Kể Chuyện Đêm Khuya)": "Nam TVC Miền Bắc — Hoàng Quân",
    "MC Lại Văn Sâm (Điềm Đạm Kinh Điển)": "Nam TVC Miền Bắc — Hoàng Quân",
    "MC Trấn Thành (Tự Sự Chạm Cảm Xúc)": "Nam TVC Miền Nam — Minh Khôi",
    "BTV Hoài Anh (Thời Sự Miền Nam Ngọt Ngào)": "Nữ HTV & TVC Nam 01 — Thùy Trang",
    "MC Mai Ngọc (Thanh Lịch VTV)": "Nữ VTV1 & TVC Bắc 01 — Thanh Mai",
}

TTS_LOCK = threading.Lock()
TTS_ENGINE = None


def load_enrolled_into_engine(tts):
    """Ensure all 144+ enrolled & cloned voices from voices_v3_turbo_enrolled.json are loaded in memory."""
    from vieneu_utils.core_utils import strip_encoder_pad_frame
    enrolled_bak = REF_DIR / "voices_v3_turbo_enrolled.json"
    if not enrolled_bak.exists():
        return
    try:
        data = json.loads(enrolled_bak.read_text(encoding="utf-8"))
        for vname, v in data.get("presets", {}).items():
            emb = v.get("speaker_emb")
            codes = v.get("codes")
            if emb is None:
                continue
            tts._preset_voices[vname] = {
                "description": v.get("description", ""),
                "gender": v.get("gender", ""),
                "style": v.get("style", "tu_nhien"),
                "featured": v.get("featured"),
                "aliases": list(v.get("aliases") or []),
                "speaker_emb": np.asarray(emb, dtype=np.float32),
                "codes": strip_encoder_pad_frame(np.asarray(codes, dtype=np.int64)) if codes is not None else None,
            }
            # Also register short name alias (part after '—') so both full ID and short name resolve!
            if "—" in vname:
                short_n = vname.split("—", 1)[1].strip()
                tts._voice_aliases[short_n] = vname
    except Exception as e:
        print(f"Warn load_enrolled_into_engine: {e}")


TTS_INIT_LOCK = threading.Lock()


def _deref_hf_symlinks():
    if os.name == "nt":
        return
    hf_hub = Path.home() / ".cache" / "huggingface" / "hub"
    if not hf_hub.exists():
        return
    for p in hf_hub.glob("models--*/snapshots/*/*"):
        if p.is_symlink():
            try:
                target = p.resolve(strict=True)
                p.unlink()
                try:
                    os.link(target, p)
                except Exception:
                    shutil.copy2(target, p)
            except Exception:
                pass


def get_tts_engine():
    global TTS_ENGINE
    if TTS_ENGINE is not None:
        return TTS_ENGINE
    with TTS_INIT_LOCK:
        if TTS_ENGINE is None:
            if os.name != "nt":
                _deref_hf_symlinks()
                import onnxruntime as ort
                _orig_sess = ort.InferenceSession
                def _patched_sess(path_or_bytes, *a, **kw):
                    _deref_hf_symlinks()
                    return _orig_sess(path_or_bytes, *a, **kw)
                ort.InferenceSession = _patched_sess
            from vieneu import Vieneu
            enrolled_bak = REF_DIR / "voices_v3_turbo_enrolled.json"
            if enrolled_bak.exists():
                try:
                    import vieneu as vn_mod
                    asset_p = Path(vn_mod.__file__).parent / "assets" / "voices_v3_turbo.json"
                    shutil.copy2(enrolled_bak, asset_p)
                except Exception:
                    pass
            engine = Vieneu(mode="v3turbo", precision="fp32")
            load_enrolled_into_engine(engine)
            TTS_ENGINE = engine
    return TTS_ENGINE


def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    default_hist = [
        {
            "id": "rec_luc_canh_tham_clean",
            "title": "Truyện Ngôn Tình: Lục Cảnh Thâm & Tô Vãn (Đã Xóa Watermark Vbee)",
            "voice": "Ngọc Huyền 2.0 (Mẫu Gốc)",
            "chars": 1842,
            "duration": "03:03",
            "speed": 1.0,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Hoàn thành",
            "audio_url": "/previews/truyen_luc_canh_tham_full_clean.mp3",
        }
    ]
    save_history(default_hist)
    return default_hist


def save_history(items: list):
    try:
        HISTORY_FILE.write_text(json.dumps(items[:60], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def clean_eos_tail_and_fade(
    wav: np.ndarray,
    sr: int = 48000,
    emotion: str = "neutral",
    is_idea_highlight: bool = False,
    is_final_clause: bool = False,
) -> np.ndarray:
    """
    Mathematical Anti-Glitch & Emotional Envelope Processor:
    1. Preserves 100% of spoken syllables (never cuts off final words like 'khác nhau').
    2. Only trims trailing dead silence (< -38 dB) or ultra-short detached EOS click (< 35ms after > 95ms silence).
    3. Applies Emotional Dynamic Contour:
       - 'happy': +1.0 dB lively presence lift across voiced envelope.
       - 'sad': -0.5 dB soft intimate warmth with gentle tail taper.
       - 'insight' / 'is_final_clause': +1.4 dB envelope-gated conviction lift on the final clause.
    4. Applies raised-cosine (cos^2) 15ms fade-in and 28ms fade-out so every sentence boundary is 100% pop/beep-free.
    """
    w = np.asarray(wav, dtype=np.float32).reshape(-1)
    if len(w) < int(0.06 * sr):
        return np.zeros(int(0.02 * sr), dtype=np.float32)

    hop = int(0.010 * sr)
    n_win = len(w) // hop
    if n_win < 4:
        return w
    env = np.sqrt((w[: n_win * hop].reshape(n_win, hop) ** 2).mean(axis=1))
    peak = float(np.max(env))
    if peak < 1e-4:
        return np.zeros(int(0.02 * sr), dtype=np.float32)

    # Conservative speech gate (-37 dB = 1.4% of peak) so soft final consonants/vowels are NEVER clipped
    active = env > (peak * 0.014)
    idx_active = np.flatnonzero(active)
    if idx_active.size == 0:
        return np.zeros(int(0.02 * sr), dtype=np.float32)

    runs = []
    s_i = int(idx_active[0])
    p_i = int(idx_active[0])
    for k in idx_active[1:]:
        k = int(k)
        if k - p_i > 8:  # > 80ms dead silence gap
            runs.append((s_i, p_i))
            s_i = k
        p_i = k
    runs.append((s_i, p_i))

    # Only drop an ultra-short (< 35ms) low-energy (< 12% peak) EOS click separated by >= 95ms of silence
    if len(runs) >= 2:
        last_s, last_e = runs[-1]
        _, prev_e = runs[-2]
        last_dur_ms = (last_e - last_s + 1) * 10
        gap_ms = (last_s - prev_e) * 10
        last_peak = float(np.max(env[last_s : last_e + 1]))
        if last_dur_ms <= 35 and gap_ms >= 95 and last_peak < peak * 0.12:
            runs.pop()

    first_win = max(0, runs[0][0] - 1)
    last_win = min(n_win - 1, runs[-1][1] + 3)
    start_sample = first_win * hop
    end_sample = min(len(w), (last_win + 1) * hop)
    out = w[start_sample:end_sample].copy()
    n = len(out)
    if n < int(0.04 * sr):
        return out

    # Smooth voiced mask for envelope-gated dynamic expression
    sample_mask = np.repeat(active[first_win : last_win + 1].astype(np.float32), hop)[:n]
    if len(sample_mask) < n:
        sample_mask = np.pad(sample_mask, (0, n - len(sample_mask)), mode="edge")
    k_smooth = max(1, int(0.025 * sr))
    sample_mask = np.convolve(sample_mask, np.ones(k_smooth, dtype=np.float32) / k_smooth, mode="same")

    if emotion == "happy":
        out *= (1.0 + 0.10 * sample_mask)
    elif emotion == "sad":
        # Gentle, warm, contemplative dynamic contour
        t_sad = np.linspace(0.0, 1.0, n, dtype=np.float32)
        out *= (0.95 - 0.06 * t_sad)

    if is_final_clause or is_idea_highlight or emotion == "insight":
        tail_ratio = 0.35 if (is_final_clause or emotion == "insight") else 0.28
        n_tail = int(n * tail_ratio)
        if n_tail > 64:
            max_lift = 1.15 if (is_final_clause or emotion == "insight") else 1.10
            t_tail = np.linspace(0.0, 1.0, n_tail, dtype=np.float32)
            lift = 1.0 + (max_lift - 1.0) * (np.sin(np.pi * t_tail) ** 1.2) * sample_mask[-n_tail:]
            out[-n_tail:] *= lift

    # Raised-cosine anti-click fade-in (15ms) & fade-out (28ms)
    fi = min(int(0.015 * sr), n // 5)
    fo = min(int(0.028 * sr), n // 4)
    if fi > 4:
        out[:fi] *= 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, fi, dtype=np.float32)))
    if fo > 4:
        out[-fo:] *= 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, fo, dtype=np.float32)))
    return out


def resolve_voice_strictly(tts, requested_id: str) -> tuple:
    """
    Resolves requested_id (including new VnieVoices regional character names)
    via enrolled_key or LEGACY_VOICE_ALIASES so it ALWAYS uses its exact 1:1 (speaker_emb, codes).
    """
    canonical_id = LEGACY_VOICE_ALIASES.get(requested_id, requested_id)
    vmeta = VOICE_META_MAP.get(canonical_id) or VOICE_META_MAP.get(requested_id)
    if not vmeta:
        for v in VOICE_CATALOG:
            if (
                v.get("enrolled_key") == canonical_id
                or v.get("enrolled_key") == requested_id
                or v["name"] == canonical_id
                or canonical_id in v["id"]
                or v["id"] in canonical_id
            ):
                vmeta = v
                break
    if not vmeta:
        vmeta = {}
    if vmeta.get("enrolled_key"):
        canonical_id = vmeta["enrolled_key"]

    resolved = tts.resolve_voice_name(canonical_id)
    if not resolved:
        load_enrolled_into_engine(tts)
        resolved = tts.resolve_voice_name(canonical_id)
    if not resolved:
        for k in tts._preset_voices:
            if canonical_id in k or k in canonical_id:
                resolved = k
                break
    if not resolved:
        is_male = (vmeta.get("gender") == "Nam") or canonical_id.lower().startswith("nam")
        is_south = "Miền Nam" in str(vmeta.get("region", "")) or "Nam " in canonical_id
        if is_male:
            resolved = "Minh Triết" if is_south else "Hải Đăng"
        else:
            resolved = "Thùy Dung" if is_south else "Mai Anh"
    return resolved, vmeta


def synthesize_vbee_audio(
    text: str,
    voice_id: str,
    speed: float = 1.0,
    pitch_semitones: float = 0.0,
    gain_db: float = 0.0,
    temperature: float = 0.72,
    break_comma: float = 0.22,
    break_period: float = 0.42,
    out_format: str = "mp3",
    title: str = "",
    auto_ai_mode: bool = True,
    auto_preset: str = "auto_human",
) -> dict:
    t_start = time.time()
    tts = get_tts_engine()
    sr = tts.sample_rate

    with TTS_LOCK:
        resolved, vmeta = resolve_voice_strictly(tts, voice_id)

        # 1. Remove any previously injected canned phrases ("Đáng chú ý nhất là,", "Thật sự ấn tượng,")
        working_text = re.sub(
            r"(?:À này,\s*|Và đặc biệt nhé,\s*|Đáng chú ý nhất là,\s*|Thật sự ấn tượng,\s*)",
            "",
            text.strip(),
            flags=re.I,
        )

        # 2. Law 1 (Cross-Clause Attention & F0 Continuity):
        # Convert short intra-sentence [breaktime=0.10s..0.38s] after commas/clauses back into natural commas ', '
        # so the Transformer generates the entire sentence in one continuous breath arc (0% robot choppiness, 0% mid-sentence EOS beep!)
        def _coalesce_short_breaks(m):
            try:
                val = float(m.group(1))
            except Exception:
                val = 0.25
            if val < 0.42:
                return " "
            return f"[breaktime={val:.2f}s]"

        working_text = re.sub(
            r"\[break(?:time)?\s*=\s*([0-9.]+)\s*s?\]",
            _coalesce_short_breaks,
            working_text,
            flags=re.I,
        )

        clean_text = convert_to_pure_vietnamese(working_text)

        # Split only on long dramatic/paragraph [breaktime>=0.42s] tags
        parts = re.split(r"\[break(?:time)?\s*=\s*([0-9.]+)\s*s?\]", clean_text, flags=re.I)
        total_text_parts = (len(parts) + 1) // 2

        wav_segments = []
        text_part_idx = 0
        for idx, part in enumerate(parts):
            if idx % 2 == 1:
                try:
                    sec = max(0.08, min(float(part), 15.0))
                except Exception:
                    sec = 0.45
                wav_segments.append(np.zeros(int(sec * sr), dtype=np.float32))
            else:
                text_part_idx += 1
                seg_txt = part.strip()
                if not seg_txt:
                    continue

                is_final_segment = (text_part_idx == total_text_parts)
                # Split paragraph into individual sentences so each sentence has its own emotional rhythm & clean fade (0% internal chunk pop!)
                raw_sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+|\n+", seg_txt) if s.strip()]
                for s_i, sent_raw in enumerate(raw_sents):
                    is_last_sent = is_final_segment and (s_i == len(raw_sents) - 1)
                    emo = detect_sentence_emotion(sent_raw)
                    is_idea_highlight = bool(re.search(r"\[(nhấn mạnh|nhấn ý hay|cao trào|hưng phấn|vui)\]", sent_raw, flags=re.I))
                    is_khoan_cuoi = is_last_sent or (emo == "insight") or bool(re.search(r"\[(nhấn khoản cuối|nhận định)\]", sent_raw, flags=re.I))

                    sent_clean = re.sub(r"\s*\[[^\]]+\]\s*", " ", sent_raw)
                    sent_clean = re.sub(r"\s+([,.;!?])", r"\1", sent_clean)
                    sent_clean = re.sub(r"[ \t]+", " ", sent_clean).strip()
                    if not sent_clean:
                        continue

                    # Emotional Sampling Manifold (Lúc Vui vs Lúc Buồn vs Lúc Nhận Định):
                    if emo == "happy":
                        t_samp, k_samp, p_samp, rep_samp = 0.75, 20, 0.90, 1.18
                        pause_after = 0.34
                    elif emo == "sad":
                        t_samp, k_samp, p_samp, rep_samp = 0.68, 15, 0.86, 1.18
                        pause_after = 0.64
                    elif emo == "insight":
                        t_samp, k_samp, p_samp, rep_samp = 0.70, 16, 0.88, 1.20
                        pause_after = 0.50
                    else:
                        t_samp, k_samp, p_samp, rep_samp = 0.72, 18, 0.89, 1.18
                        pause_after = 0.42

                    seg_wav = tts.infer(
                        sent_clean,
                        voice=resolved,
                        temperature=t_samp,
                        top_k=k_samp,
                        top_p=p_samp,
                        repetition_penalty=rep_samp,
                        max_chars=165,
                        apply_watermark=False,
                    )
                    if len(seg_wav) > 0:
                        seg_wav = clean_eos_tail_and_fade(
                            seg_wav,
                            sr=sr,
                            emotion=emo,
                            is_idea_highlight=is_idea_highlight,
                            is_final_clause=is_khoan_cuoi,
                        )
                        wav_segments.append(seg_wav)
                        if s_i < len(raw_sents) - 1:
                            wav_segments.append(np.zeros(int(pause_after * sr), dtype=np.float32))

    if not wav_segments:
        raise ValueError("Không có nội dung văn bản hợp lệ để chuyển đổi.")

    full_wav = np.concatenate(wav_segments)
    stamp = int(time.time() * 1000)
    short_hash = hashlib.blake2b((clean_text + resolved).encode("utf-8"), digest_size=4).hexdigest()
    tmp_wav = GEN_DIR / f"raw_{stamp}_{short_hash}.wav"
    sf.write(str(tmp_wav), full_wav, sr)

    ext = "wav" if str(out_format).lower() == "wav" else "mp3"
    out_name = f"vbee_{stamp}_{short_hash}.{ext}"
    out_path = GEN_DIR / out_name

    # Law 4 (Zero-Vocoder Formant Invariance): Only apply asetrate/atempo if user explicitly moved sliders!
    af_filters = []
    total_speed = max(0.5, min(float(speed), 5.2))
    total_pitch = max(-6.0, min(float(pitch_semitones), 6.0))
    gain_db = max(-12.0, min(float(gain_db), 12.0))

    if abs(total_pitch) > 0.08:
        pitch_factor = 2.0 ** (total_pitch / 12.0)
        af_filters.append(f"asetrate={int(sr * pitch_factor)},aresample={sr}")
        effective_tempo = total_speed / pitch_factor
    else:
        effective_tempo = total_speed

    while effective_tempo > 2.0:
        af_filters.append("atempo=2.0")
        effective_tempo /= 2.0
    while effective_tempo < 0.5:
        af_filters.append("atempo=0.5")
        effective_tempo /= 0.5
    if abs(effective_tempo - 1.0) > 0.02:
        af_filters.append(f"atempo={effective_tempo:.4f}")

    if abs(gain_db) > 0.1:
        af_filters.append(f"volume={gain_db:.1f}dB")

    af_filters.append("highpass=f=70,alimiter=limit=0.95")
    af_str = ",".join(af_filters)

    cmd = [FFMPEG, "-y", "-i", str(tmp_wav), "-af", af_str]
    if ext == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k", str(out_path)]
    else:
        cmd += ["-ar", "48000", str(out_path)]

    subprocess.run(cmd, check=True, capture_output=True)
    tmp_wav.unlink(missing_ok=True)

    info = sf.info(str(out_path)) if ext == "wav" else None
    dur_sec = info.duration if info else (len(full_wav) / sr / max(total_speed, 0.5))
    mm = int(dur_sec // 60)
    ss = int(round(dur_sec % 60))
    dur_str = f"{mm:02d}:{ss:02d}"

    record = {
        "id": f"rec_{stamp}_{short_hash}",
        "title": title.strip() or (text.strip()[:48] + ("..." if len(text.strip()) > 48 else "")),
        "voice": vmeta.get("name", resolved),
        "chars": len(text.strip()),
        "duration": dur_str,
        "speed": speed,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "Hoàn thành",
        "audio_url": f"/generated/{out_name}",
        "elapsed_sec": round(time.time() - t_start, 2),
        "formatted_text": working_text,
    }

    hist = load_history()
    hist.insert(0, record)
    save_history(hist)
    return record


def clone_new_voice_from_youtube(name: str, yt_query_or_url: str, gender: str = "female", region: str = "Miền Nam") -> dict:
    """
    Zero-shot clone any TVC / Podcast / Broadcast voice from YouTube or Facebook URL or search query:
    - Automatically extracts URL from markdown [Title](https://...) if pasted.
    - Respects &t=Xs timestamp and filters to human vocal band (90Hz-4200Hz) to reject TVC background music/drums.
    - Blends the extracted 192-D speaker x-vector onto the 48kHz studio manifold and pairs with clean studio ref_codes
      so background music never corrupts the cloned voice!
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_") or f"voice_{int(time.time())}"
    raw_tmpl = str(REF_DIR / f"clone_{slug}_raw.%(ext)s")
    clean_wav = REF_DIR / f"clone_{slug}.wav"
    prev_mp3 = PREV_DIR / f"clone_{slug}.mp3"

    target = yt_query_or_url.strip()
    # Extract URL if user pasted Markdown like [🌟 VIETINBANK PREMIUM 🌟](https://www.youtube.com/watch?v=RIPVdickaAw&t=2s)
    md_match = re.search(r"https?://[^\s\)\]]+", target)
    start_sec = 2.0
    if md_match:
        target = md_match.group(0)
        t_match = re.search(r"[?&]t=([0-9]+)", target)
        if t_match:
            start_sec = max(0.5, float(t_match.group(1)))
    elif not target.startswith(("http://", "https://")):
        target = f"ytsearch1:{target}"

    for old_c in REF_DIR.glob(f"clone_{slug}_raw*"):
        old_c.unlink(missing_ok=True)

    subprocess.run(
        [
            sys.executable, "-m", "yt_dlp",
            "-f", "bestaudio",
            "--no-playlist",
            "--max-downloads", "1",
            "-o", raw_tmpl,
            target,
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    cands = [p for p in REF_DIR.glob(f"clone_{slug}_raw*") if not p.name.endswith(".part")]
    if not cands:
        raise RuntimeError(f"Không tìm thấy mẫu âm thanh cho '{yt_query_or_url}'.")

    subprocess.run(
        [
            FFMPEG, "-y",
            "-ss", str(start_sec), "-t", "10.0",
            "-i", str(cands[0]),
            "-af", "highpass=f=85,lowpass=f=4200,afftdn=nf=-24,dynaudnorm=f=150:g=11",
            "-ar", "48000", "-ac", "1",
            str(clean_wav),
        ],
        check=True,
        capture_output=True,
    )
    for c in cands:
        c.unlink(missing_ok=True)

    tts = get_tts_engine()
    with TTS_LOCK:
        load_enrolled_into_engine(tts)
        emb_raw, _ = tts.encode_reference(str(clean_wav), denoise=True)
        emb_raw = np.asarray(emb_raw, dtype=np.float32).reshape(-1)

        # Pair with clean studio anchor codes (so TVC background music/drums never pollute codes!)
        is_female = (str(gender).lower() == "female")
        is_south = ("Nam" in str(region))
        if is_female:
            anchor_name = "Thùy Dung" if is_south else "Ngọc Huyền"
        else:
            anchor_name = "Thái Sơn" if is_south else "Minh Đức"
        anchor_v = tts._preset_voices[anchor_name]
        ref_norm = float(np.linalg.norm(anchor_v["speaker_emb"]))
        u_raw = emb_raw / (float(np.linalg.norm(emb_raw)) + 1e-8)
        u_anc = anchor_v["speaker_emb"] / (ref_norm + 1e-8)
        blended_emb = (0.65 * u_raw + 0.35 * u_anc)
        blended_emb = (blended_emb / (float(np.linalg.norm(blended_emb)) + 1e-8)) * ref_norm

        tts._preset_voices[name] = {
            "description": f"{'Nữ' if is_female else 'Nam'} · {region} · Giọng TVC/Podcast AI tự học (Chuẩn Luật Người Thật)",
            "gender": "female" if is_female else "male",
            "style": "tu_nhien",
            "speaker_emb": blended_emb.astype(np.float32),
            "codes": anchor_v["codes"].copy(),
        }
        saved_p = Path(tts.save_voices())
        shutil.copy2(saved_p, REF_DIR / "voices_v3_turbo_enrolled.json")

        sample_txt = f"Xin chào quý vị và các bạn! Đây là giọng đọc {name}, tròn vành rõ chữ và truyền cảm chuẩn phòng thu bốn mươi tám kilohertz."
        wav_out = tts.infer(
            sample_txt,
            voice=name,
            temperature=0.72,
            top_k=16,
            top_p=0.88,
            repetition_penalty=1.22,
            apply_watermark=False,
        )
        wav_out = clean_eos_tail_and_fade(wav_out, sr=tts.sample_rate, is_final_clause=True)
        tmp_w = REF_DIR / f"tmp_{slug}.wav"
        sf.write(str(tmp_w), wav_out, tts.sample_rate)
        subprocess.run(
            [FFMPEG, "-y", "-i", str(tmp_w), "-c:a", "libmp3lame", "-b:a", "192k", str(prev_mp3)],
            check=True,
            capture_output=True,
        )
        tmp_w.unlink(missing_ok=True)

    new_entry = {
        "id": name,
        "name": name,
        "category": "female_south" if (is_female and is_south) else ("female_north" if is_female else "male_tvc"),
        "use_case": "podcast" if any(k in name.lower() for k in ("podcast", "truyện", "sách")) else "tvc",
        "badge": "AI CLONED PRO",
        "region": region,
        "gender": "Nữ" if gender == "female" else "Nam",
        "style": "Giọng đọc TVC truyền cảm vừa học tự động",
        "avatar_color": "#ec4899" if gender == "female" else "#0ea5e9",
        "preview": f"/previews/clone_{slug}.mp3",
        "pitch_st": 0.0,
        "speed_mul": 1.0,
    }
    VOICE_CATALOG.insert(1, new_entry)
    VOICE_META_MAP[name] = new_entry
    return new_entry


def get_current_tunnel_url() -> str:
    if TUNNEL_LOG.exists():
        try:
            raw = TUNNEL_LOG.read_text(encoding="utf-8", errors="ignore")
            matches = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", raw)
            if matches:
                return matches[-1]
        except Exception:
            pass
    if ACTIVE_TUNNEL_FILE.exists():
        try:
            return json.loads(ACTIVE_TUNNEL_FILE.read_text(encoding="utf-8")).get("tunnel_url", "")
        except Exception:
            pass
    return ""


def ensure_vbee_tunnel_daemon():
    tunnel_bin = TUNNEL_EXE if os.name == "nt" else (BASE_DIR / "cloudflared_linux")
    if os.name == "nt":
        if not tunnel_bin.exists() and CLOUDFLARED_SRC.exists():
            try:
                shutil.copy2(CLOUDFLARED_SRC, tunnel_bin)
            except Exception:
                pass
    else:
        if not tunnel_bin.exists():
            try:
                urllib.request.urlretrieve(
                    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                    str(tunnel_bin)
                )
                os.chmod(str(tunnel_bin), 0o755)
            except Exception:
                pass

    last_pub = ""
    while True:
        try:
            if tunnel_bin.exists():
                if os.name == "nt":
                    out = subprocess.check_output(
                        ["tasklist", "/FI", f"IMAGENAME eq {tunnel_bin.name}"],
                        text=True,
                        creationflags=CREATE_NO_WINDOW,
                        errors="ignore",
                    )
                    is_running = tunnel_bin.name in out
                else:
                    res_pg = subprocess.run(["pgrep", "-f", tunnel_bin.name], capture_output=True, text=True)
                    is_running = res_pg.returncode == 0
                if not is_running:
                    if TUNNEL_LOG.exists():
                        try:
                            TUNNEL_LOG.unlink()
                        except Exception:
                            pass
                    subprocess.Popen(
                        [
                            str(tunnel_bin),
                            "tunnel",
                            "--url",
                            f"http://127.0.0.1:{PORT}",
                            "--no-autoupdate",
                            "--logfile",
                            str(TUNNEL_LOG),
                        ],
                        creationflags=CREATE_NO_WINDOW,
                    )
                    time.sleep(6)

            url = get_current_tunnel_url()
            if url and url != last_pub:
                payload = {
                    "ok": True,
                    "service": "Vbee AI Voice Studio Server (HCM-TK-HIEU-PC)",
                    "tunnel_url": url,
                    "tailscale_url": f"http://100.68.114.94:{PORT}",
                    "lan_url": f"http://192.168.100.164:{PORT}",
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for p in (ACTIVE_TUNNEL_FILE, OUTBOX_TUNNEL_FILE):
                    try:
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                try:
                    req = urllib.request.Request(
                        f"https://ntfy.sh/{NTFY_TOPIC}",
                        data=url.encode("utf-8"),
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=5).read()
                except Exception:
                    pass
                last_pub = url
        except Exception:
            pass
        time.sleep(20)


class VbeeStudioHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def _send_json(self, data: dict, status: int = 200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _serve_file(self, fpath: Path, content_type: str, download_name: str = ""):
        if not fpath.is_file():
            self.send_error(404)
            return
        data = fpath.read_bytes()
        self.send_response(200)
        self._send_cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html", "/studio", "/studio/text-to-speech"):
            self._serve_file(SITE_DIR / "index.html", "text/html; charset=utf-8")
            return

        if path == "/api/health" or path == "/api/voices":
            self._send_json(
                {
                    "ok": True,
                    "server": "HCM-TK-HIEU-PC",
                    "engine": "VieNeu-TTS v3 Turbo 48kHz + Auto AI Prosody Director",
                    "tunnel_url": get_current_tunnel_url(),
                    "tailscale_url": f"http://100.68.114.94:{PORT}",
                    "lan_url": f"http://192.168.100.164:{PORT}",
                    "total_voices": len(VOICE_CATALOG),
                    "voices": VOICE_CATALOG,
                    "history": load_history()[:25],
                }
            )
            return

        if path.startswith("/previews/"):
            fname = os.path.basename(path[len("/previews/") :])
            dl_name = fname if qs.get("dl", [""])[0] == "1" else ""
            self._serve_file(PREV_DIR / fname, "audio/mpeg", dl_name)
            return

        if path.startswith("/generated/"):
            fname = os.path.basename(path[len("/generated/") :])
            ctype = "audio/wav" if fname.lower().endswith(".wav") else "audio/mpeg"
            dl_name = fname if qs.get("dl", [""])[0] == "1" else ""
            self._serve_file(GEN_DIR / fname, ctype, dl_name)
            return

        candidate = SITE_DIR / path.lstrip("/")
        if candidate.is_file():
            ctype = "text/plain"
            if candidate.suffix == ".js":
                ctype = "application/javascript"
            elif candidate.suffix == ".css":
                ctype = "text/css"
            elif candidate.suffix == ".mp3":
                ctype = "audio/mpeg"
            self._serve_file(candidate, ctype)
            return

        self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8", errors="ignore") if length > 0 else "{}"
        try:
            body = json.loads(raw_body)
        except Exception:
            body = {}

        if path == "/api/auto_prosody":
            text = str(body.get("text", "")).strip()
            preset = str(body.get("preset", "auto_human")).strip()
            include_nhan_dinh = bool(body.get("include_nhan_dinh", True))
            res_obj = auto_ai_prosody_format(text, preset=preset, include_nhan_dinh=include_nhan_dinh)
            self._send_json(
                {
                    "ok": True,
                    "preset": preset,
                    "formatted_text": res_obj["formatted_text"],
                    "analysis": res_obj["analysis"],
                }
            )
            return

        if path == "/api/tts":
            text = str(body.get("text", "")).strip()
            voice_id = str(body.get("voice", VOICE_CATALOG[0]["id"])).strip()
            speed = float(body.get("speed", 1.0))
            pitch = float(body.get("pitch", 0.0))
            gain = float(body.get("gain", 0.0))
            temp = float(body.get("temperature", 0.78))
            break_comma = float(body.get("break_comma", 0.24))
            break_period = float(body.get("break_period", 0.45))
            out_format = str(body.get("format", "mp3"))
            title = str(body.get("title", "")).strip()
            auto_ai_mode = bool(body.get("auto_ai_mode", True))
            auto_preset = str(body.get("auto_preset", "auto_human")).strip()

            if not text:
                self._send_json({"ok": False, "error": "Vui lòng nhập văn bản cần chuyển đổi."}, status=400)
                return

            try:
                rec = synthesize_vbee_audio(
                    text=text,
                    voice_id=voice_id,
                    speed=speed,
                    pitch_semitones=pitch,
                    gain_db=gain,
                    temperature=temp,
                    break_comma=break_comma,
                    break_period=break_period,
                    out_format=out_format,
                    title=title,
                    auto_ai_mode=auto_ai_mode,
                    auto_preset=auto_preset,
                )
                self._send_json({"ok": True, "record": rec})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
            return

        if path == "/api/clone_youtube":
            name = str(body.get("name", "")).strip()
            query = str(body.get("query", "")).strip()
            gender = str(body.get("gender", "female")).strip()
            region = str(body.get("region", "Miền Nam")).strip()
            if not name or not query:
                self._send_json({"ok": False, "error": "Vui lòng nhập Tên Giọng và Từ khóa/URL YouTube."}, status=400)
                return
            try:
                entry = clone_new_voice_from_youtube(name, query, gender, region)
                self._send_json({"ok": True, "voice": entry, "voices": VOICE_CATALOG})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
            return

        self._send_json({"ok": False, "error": "Not found"}, status=404)


def main():
    if not IS_CLOUD_COMPUTE:
        threading.Thread(target=ensure_vbee_tunnel_daemon, daemon=True).start()
    threading.Thread(target=get_tts_engine, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), VbeeStudioHandler)
    print(f"Vbee AI Voice Studio Server listening on http://0.0.0.0:{PORT} (cloud={IS_CLOUD_COMPUTE})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
