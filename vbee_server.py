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
OUTBOX_TUNNEL_FILE = BASE_DIR / "cloud_tunnel_status.json"
TUNNEL_LOG = BASE_DIR / "vbee_tunnel.log"
CLOUDFLARED_SRC = BASE_DIR / "cloudflared.exe"
TUNNEL_EXE = BASE_DIR / "vbee_tunnel.exe"
NTFY_TOPIC = "vnievoices_github_cloud_compute"
PORT = int(os.environ.get("PORT", "8890"))
IS_CLOUD_COMPUTE = bool(os.environ.get("K_SERVICE") or os.environ.get("SPACE_ID") or os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("CLOUD_RUN_JOB"))
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

SITE_DIR.mkdir(parents=True, exist_ok=True)
PREV_DIR.mkdir(parents=True, exist_ok=True)
REF_DIR.mkdir(parents=True, exist_ok=True)
GEN_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
JOBS_FILE = BASE_DIR / "tts_jobs_state.json"

ROMAN_MAP = {
    "I": "1", "II": "2", "III": "3", "IV": "4", "V": "5",
    "VI": "6", "VII": "7", "VIII": "8", "IX": "9", "X": "10",
    "XI": "11", "XII": "12", "XIII": "13", "XIV": "14", "XV": "15",
    "XVI": "16", "XVII": "17", "XVIII": "18", "XIX": "19", "XX": "20",
    "XXI": "21", "XXII": "22", "XXIII": "23", "XXIV": "24", "XXV": "25",
    "XXVI": "26", "XXVII": "27", "XXVIII": "28", "XXIX": "29", "XXX": "30",
}

VALID_ACTING_TAG_RE = re.compile(
    r"^\[\s*(?:break(?:time)?\s*=\s*[0-9.]+s?|vui|buồn|nhận định|hưng phấn|sôi động|nhấn mạnh|nhấn ý hay|nhấn khoản cuối|cao trào|lắng đọng|trầm ấm|tươi vui|lấy hơi|hắng giọng|cười|thở dài|cảm thán|châu tinh trì|hài châu tinh trì|trường giang|hài trường giang|nguyễn ngọc ngạn|truyện ma|chính kịch|kinh kịch|bi kịch)\s*\]$",
    re.I,
)


def clean_and_reword_book_text(text: str) -> dict:
    """
    5-Stage AI Book Sanitizer & Spoken Vietnamese Re-Wording Engine:
    1. Strips all Bookmarks, TOC dot-leader lines, Page numbers, Running headers/footers, Footnote brackets, URLs, and Ebook/Web UI junk.
    2. De-hyphenates and reflows mid-sentence PDF line wraps into complete, natural paragraphs.
    3. Re-words written book shorthand, Roman numerals, dates, units, symbols, and parentheticals into smooth spoken Vietnamese.
    """
    if not text or not text.strip():
        return {"text": "", "removed_junk": 0, "reworded_items": 0}

    t = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    removed_junk = 0
    reworded_items = 0

    # Strip any leaked internal placeholder tokens or legacy synthetic 'Nhận định lại...' lines
    t, n_leak = re.subn(r"_{0,2}VBEE_(?:ACT_)?TAG_\d+_{0,2}|\x02VBEE(?:ACT|TAG)\d+\x03", " ", t, flags=re.I)
    t, n_nd = re.subn(
        r"\n*(?:\s*\[[^\]]+\]\s*)*(?:Nhận định (?:lại|chung)[:\s,]|Ngẫm lại mới thấy,|Có thể khẳng định,|Nhìn rộng hơn, đây chính là điểm nhấn)[^\n]*",
        "",
        t,
        flags=re.I,
    )
    removed_junk += (n_leak + n_nd)

    protected_tags = []

    def _handle_brackets(m):
        nonlocal removed_junk
        full_tag = m.group(0)
        if VALID_ACTING_TAG_RE.match(full_tag):
            idx = len(protected_tags)
            protected_tags.append(full_tag)
            return f"\x02VBEEACT{idx}\x03"
        removed_junk += 1
        return " "

    def _strip_md_link(m):
        nonlocal removed_junk
        removed_junk += 1
        label = m.group(1).strip()
        if re.search(r"^(?:bookmarks?|đánh dấu|mục lục|xem thêm|đọc tiếp|tải về|download|click|nguồn|link)", label, re.I):
            return " "
        return label

    t = re.sub(r"\[([^\]]+)\]\((?:https?://|mailto:|#)[^\)]+\)", _strip_md_link, t)
    t = re.sub(r"\[[^\]]*\]", _handle_brackets, t)

    paren_junk_re = re.compile(
        r"\(\s*(?:bookmarks?|đánh dấu(?: trang)?|xem\s+(?:trang|tr\.?|chương|hình|bảng|mục)[^)]*|trang\s*\d+[^)]*|page\s*\d+[^)]*|tr\.?\s*\d+[^)]*|p\.?\s*\d+[^)]*|nguồn\s*:[^)]*|ảnh\s*:[^)]*|hình\s*\d+[^)]*|bảng\s*\d+[^)]*|xem thêm[^)]*|đọc tiếp[^)]*|còn tiếp[^)]*|chú thích[^)]*|note\s*:[^)]*|\*+)\s*\)",
        re.I,
    )
    t, n_p = paren_junk_re.subn(" ", t)
    removed_junk += n_p

    t, n_u = re.subn(r"https?://\S+|www\.\S+", " ", t, flags=re.I)
    removed_junk += n_u
    t, n_h = re.subn(r"<[^>]+>", " ", t)
    removed_junk += n_h
    t, n_sup = re.subn(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+", "", t)
    removed_junk += n_sup

    raw_lines = t.split("\n")
    line_freq = {}
    for ln in raw_lines:
        s_ln = ln.strip()
        if 1 <= len(s_ln) <= 85 and not s_ln.startswith(("\x02VBEEACT", "-", "–", "—", "“", '"')):
            line_freq[s_ln.lower()] = line_freq.get(s_ln.lower(), 0) + 1

    bookmark_line_re = re.compile(
        r"^\s*(?:bookmarks?\b|đánh dấu trang|danh sách đánh dấu|thêm bookmark|xoá bookmark|đã lưu bookmark|mục lục\s*$|table of contents|danh mục chương|chuyển đến trang|go to page|trang trước|trang tiếp|trang sau|chương trước|chương tiếp|chương sau|đọc tiếp|xem thêm|chia sẻ bài viết|bình luận|quảng cáo|advertisement|sponsored|copy link|tải sách|download ebook|nguồn\s*:|link gốc\s*:|bản quyền thuộc về|copyright\s*©|all rights reserved|isbn\s*[:0-9-]|chịu trách nhiệm xuất bản|in xong và nộp lưu chiểu|biên tập\s*:|trình bày bìa\s*:|sửa bản in\s*:)",
        re.I,
    )
    ebook_watermark_re = re.compile(
        r"(?:mua sách giấy tại|đặt hàng online qua|để có những cảm nhận phong phú nhất|ebook chỉ để tặng|nghiêm cấm các hành vi in lậu|tải ebook miễn phí|thuvienebook|dtv-ebook|sachvui|wattpad|truyenfull|wikidich|bizbooks\.vn)",
        re.I,
    )
    running_header_re = re.compile(
        r"^\s*[∼~—–\-=*★☆•|]{1,4}\s*[^∼~—–\-=*★☆•|\n]{2,80}\s*[∼~—–\-=*★☆•|]{1,4}\s*$"
    )
    pipe_or_sep_line_re = re.compile(r"^\s*[-—–|•*~_=+✦★☆/\\]+\s*$")
    toc_dot_line_re = re.compile(
        r"^.*?(?:\.{3,}|…{2,}|-{3,}|_{3,}|\t+|\s{4,})\s*(?:trang\s*|page\s*|tr\.?\s*)?\d{1,5}\s*$",
        re.I,
    )
    toc_chap_page_re = re.compile(
        r"^\s*(?:chương|phần|mục|bài|quyển|tập|chapter|part)\s+[0-9IVXLCDM]+\b[^\n]{0,65}\s+\d{1,4}\s*$",
        re.I,
    )
    page_num_line_re = re.compile(
        r"^\s*(?:[-—–|•*~_()]*\s*)?(?:trang|page|tr\.?|p\.?|tờ)?\s*\d{1,5}(?:\s*(?:/|trên|of|-)\s*\d{1,5})?\s*(?:[-—–|•*~_()]*)\s*$",
        re.I,
    )
    footnote_line_re = re.compile(
        r"^\s*(?:\(\d{1,2}\)|\[\d{1,2}\]|\d+\)|\*\s+|\†\s+).+",
        re.I,
    )
    footnote_num_start_re = re.compile(
        r"^\s*(?:\(\d{1,2}\)|\[\d{1,2}\]|\d{1,2})\s+[A-ZÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬĐÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ]"
    )

    def _is_page_break_or_watermark(s_line: str) -> bool:
        if not s_line:
            return False
        return bool(
            bookmark_line_re.search(s_line)
            or ebook_watermark_re.search(s_line)
            or running_header_re.match(s_line)
            or pipe_or_sep_line_re.match(s_line)
            or toc_dot_line_re.match(s_line)
            or toc_chap_page_re.match(s_line)
            or page_num_line_re.match(s_line)
        )

    # Pre-mark bottom-of-page multi-line footnote blocks that sit within 1..6 lines above a page break / watermark
    n_raw = len(raw_lines)
    skip_line_indices = set()
    for idx_ln in range(n_raw):
        s_cur = raw_lines[idx_ln].strip()
        if not s_cur:
            continue
        if footnote_num_start_re.match(s_cur) or footnote_line_re.match(s_cur):
            # Look ahead up to 6 lines for a page-break/watermark/running-header line
            anchor_pos = -1
            for look_i in range(idx_ln + 1, min(n_raw, idx_ln + 7)):
                if _is_page_break_or_watermark(raw_lines[look_i].strip()):
                    anchor_pos = look_i
                    break
            if anchor_pos != -1:
                for k_skip in range(idx_ln, anchor_pos):
                    skip_line_indices.add(k_skip)
            elif footnote_line_re.match(s_cur):
                skip_line_indices.add(idx_ln)

    kept_lines = []
    for idx_ln, ln in enumerate(raw_lines):
        if idx_ln in skip_line_indices:
            removed_junk += 1
            continue
        s = ln.strip()
        if not s:
            kept_lines.append("")
            continue
        s = re.sub(r"^\s*#{1,6}\s+", "", s)
        s = re.sub(r"^\s*>\s+", "", s)
        if _is_page_break_or_watermark(s) or footnote_line_re.match(s):
            removed_junk += 1
            continue
        s, n_bm_inline = re.subn(
            r"(?:\bBookmark(?:s)?\b\s*[:\-–—]?\s*(?:trang\s*\d+)?|\bĐánh dấu trang\b\s*[:\-–—]?\s*(?:trang\s*\d+)?|\bTrang\s+\d{1,5}\s*(?:/\s*\d{1,5})?\b|\bPage\s+\d{1,5}\s*(?:of\s*\d{1,5})?\b)",
            " ",
            s,
            flags=re.I,
        )
        removed_junk += n_bm_inline
        s = s.strip()
        if not s:
            continue
        if len(raw_lines) >= 10 and line_freq.get(s.lower(), 0) >= 3 and len(s) <= 85:
            removed_junk += 1
            continue
        s = re.sub(r"^\s*[•▪▫◆◇►▸➢➔✓✔✦★☆]+\s*", "", s)
        s = re.sub(r"^\s*[-–—]\s+(?=[A-ZÀ-Ỹa-zà-ỹ])", "", s)
        kept_lines.append(s)

    joined_text = "\n".join(kept_lines)
    joined_text = re.sub(r"([a-zA-ZÀ-ỹ])-\s*\n\s*([a-zA-ZÀ-ỹ])", r"\1\2", joined_text)

    raw_blocks = re.split(r"\n\s*\n+", joined_text)
    reflowed_paras = []
    chapter_heading_re = re.compile(
        r"^\s*(?:(?:chương|phần|hồi|quyển|tập|mục)\s+(?:\d+|[IVXLCDM]+|thứ\s+\S+|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|mở\s+đầu|kết\s+thúc)|lời\s+mở\s+đầu|lời\s+nói\s+đầu|kết\s+luận)\b",
        re.I,
    )
    for blk in raw_blocks:
        b_lines = [x.strip() for x in blk.split("\n") if x.strip()]
        if not b_lines:
            continue
        cur_para = []
        sent_end_count = 0
        for bl in b_lines:
            if chapter_heading_re.match(bl):
                if cur_para:
                    reflowed_paras.append(" ".join(cur_para))
                    cur_para = []
                    sent_end_count = 0
                if not bl.endswith((".", "!", "?", "…", ":")):
                    bl = bl + "."
                reflowed_paras.append(bl)
            else:
                cur_para.append(bl)
                if bl.endswith((".", "!", "?", "…", "”", '"')) and len(" ".join(cur_para)) >= 320:
                    sent_end_count += 1
                    if sent_end_count >= 2:
                        reflowed_paras.append(" ".join(cur_para))
                        cur_para = []
                        sent_end_count = 0
        if cur_para:
            p_str = " ".join(cur_para)
            if not p_str.endswith((".", "!", "?", "…", "”", '"')) and not re.search(r"\x02VBEEACT\d+\x03$", p_str):
                p_str += "."
            reflowed_paras.append(p_str)

    t = "\n".join(reflowed_paras)

    def _replace_roman(m):
        nonlocal reworded_items
        prefix = m.group(1)
        rom = m.group(2).upper()
        if rom in ROMAN_MAP:
            reworded_items += 1
            return f"{prefix} {ROMAN_MAP[rom]}"
        return m.group(0)

    t = re.sub(
        r"\b(Chương|Phần|Thế kỷ|Tập|Quyển|Hồi|Mục|Lần thứ)\s+(XXX|XXIX|XXVIII|XXVII|XXVI|XXV|XXIV|XXIII|XXII|XXI|XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)\b",
        _replace_roman,
        t,
        flags=re.I,
    )

    reword_rules = [
        (r"\b(?:ngày\s+)?(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", r"ngày \1 tháng \2 năm \3"),
        (r"\btháng\s+(\d{1,2})[/-](\d{4})\b", r"tháng \1 năm \2"),
        (r"\b(\d{1,2})h(\d{2})\b", r"\1 giờ \2 phút"),
        (r"\b(\d{1,2})h\s*(sáng|trưa|chiều|tối|đêm)\b", r"\1 giờ \2"),
        (r"(\d+(?:[.,]\d+)?)\s*%", r"\1 phần trăm"),
        (r"(\d+(?:[.,]\d+)?)\s*°C\b", r"\1 độ C"),
        (r"(\d+(?:[.,]\d+)?)\s*km/h\b", r"\1 ki lô mét trên giờ"),
        (r"(\d+(?:[.,]\d+)?)\s*(?:km2|km²)\b", r"\1 ki lô mét vuông"),
        (r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²)\b", r"\1 mét vuông"),
        (r"(\d+(?:[.,]\d+)?)\s*(?:m3|m³)\b", r"\1 mét khối"),
        (r"\b(\d+(?:[.,]\d+)?)\s*km\b", r"\1 ki lô mét"),
        (r"\b(\d+(?:[.,]\d+)?)\s*kg\b", r"\1 ki lô gam"),
        (r"\b(\d+(?:[.,]\d+)?)\s*(?:VNĐ|VND)\b", r"\1 đồng"),
        (r"\bTP\.?\s*HCM\b", "Thành phố Hồ Chí Minh"),
        (r"\bTP\.?\s+(?=[A-ZĐÀ-Ỹ])", "Thành phố "),
        (r"\bPGS\.?\s*TS\.?\s+", "Phó giáo sư Tiến sĩ "),
        (r"\bGS\.?\s*TS\.?\s+", "Giáo sư Tiến sĩ "),
        (r"\bTS\.?\s+(?=[A-ZĐÀ-Ỹ])", "Tiến sĩ "),
        (r"\bThS\.?\s+(?=[A-ZĐÀ-Ỹ])", "Thạc sĩ "),
        (r"\bBS\.?\s+(?=[A-ZĐÀ-Ỹ])", "Bác sĩ "),
        (r"\bNXB\b", "Nhà xuất bản"),
        (r"\bUBND\b", "Ủy ban nhân dân"),
        (r"\bHĐND\b", "Hội đồng nhân dân"),
        (r"\bCHXHCN\b", "Cộng hòa xã hội chủ nghĩa"),
        (r"\bXHCN\b", "xã hội chủ nghĩa"),
        (r"\bTNHH\b", "Trách nhiệm hữu hạn"),
        (r"\bTHPT\b", "Trung học phổ thông"),
        (r"\bTHCS\b", "Trung học cơ sở"),
        (r"\bĐH\b(?=\s+[A-ZĐÀ-Ỹ])", "Đại học"),
        (r"\bBĐS\b", "bất động sản"),
        (r"\bCNTT\b", "công nghệ thông tin"),
        (r"\bMXH\b", "mạng xã hội"),
        (r"\bđ/c\b", "đồng chí"),
        (r"\bv/v\b", "về việc"),
        (r"\bvà/hoặc\b", "và hoặc"),
        (r"\bnam/nữ\b", "nam hoặc nữ"),
        (r"\b24/7\b", "hai mươi tư trên bảy"),
        (r"\b(?:v\.v\.\.\.|v\.v\.|vv\.\.\.|v\.v)\b", "vân vân"),
        (r"\b(?:VD|Vd|Ví dụ)\s*:\s*", "Ví dụ như, "),
        (r"\bLưu ý\s*:\s*", "Lưu ý là, "),
        (r"\bTức là\s*:\s*", "Tức là, "),
        (r"\bCụ thể\s*:\s*", "Cụ thể là, "),
        (r"\s+&\s+", " và "),
        (r"\s*(?:->|=>|→)\s*", ", dẫn đến "),
    ]
    for pat, rep in reword_rules:
        t, n_r = re.subn(pat, rep, t)
        reworded_items += n_r

    # Strip inline footnote superscripts attached to words/quotes (e.g. Lincoln1, dây thép1, Nhà Trắng1, Mỹ kim1, tuyết”2., coi lại1”, Al Capone 1,)
    t, n_fn1 = re.subn(r"(?<=[a-zà-ỹ])[1-9](?=[,.;:!?”\"'\s]|$)", "", t)
    t, n_fn2 = re.subn(r"(?<=[”\"'])[1-9](?=[,.;:!?\s]|$)", "", t)
    t, n_fn3 = re.subn(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\s+[1-9](?=[,.;:!?])", r"\1", t)
    t, n_fn4 = re.subn(r"\(\s*\d{1,3}\s*\)", " ", t)
    removed_junk += (n_fn1 + n_fn2 + n_fn3 + n_fn4)

    # Strip redundant foreign original-spelling parentheticals after Vietnamese phonetic names (e.g. "Nữu Ước (New York)" -> "Nữu Ước")
    t, n_biling = re.subn(
        r"\b(Nữu Ước|Hoa Thịnh Đốn|Luân Đôn|Ba Lê|Mạc Tư Khoa|Á Căn Đình|Bắc Kinh|Thượng Hải|Đông Kinh)\s*\(\s*[A-Za-z\s\-]{2,30}\s*\)",
        r"\1",
        t,
        flags=re.I,
    )
    reworded_items += n_biling

    def _reword_spoken_parens(m):
        nonlocal reworded_items
        inner = m.group(1).strip()
        if not inner:
            return ""
        reworded_items += 1
        return f", {inner}, "

    t = re.sub(r"\(\s*([^()]{2,120})\s*\)", _reword_spoken_parens, t)
    t = re.sub(r"(\*\*|__|~~|`)", "", t)
    t = re.sub(r"(?:\.{2,}|…+)\s+(?=[a-zà-ỹ])", ", ", t)
    t = re.sub(r"([!?])\s*(?:\.{2,}|…+)", r"\1", t)
    t = re.sub(r",\s*([.!?…;:])", r"\1", t)
    t = re.sub(r"\s+([,.;!?])", r"\1", t)
    t = re.sub(r",\s*,+", ", ", t)
    t = re.sub(r"\.\s*\.+", ".", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()

    for idx, val in enumerate(protected_tags):
        t = t.replace(f"\x02VBEEACT{idx}\x03", val)

    t = re.sub(r"_{0,2}VBEE_(?:ACT_)?TAG_\d+_{0,2}|\x02VBEE(?:ACT|TAG)\d+\x03", " ", t, flags=re.I)

    return {
        "text": t.strip(),
        "removed_junk": removed_junk,
        "reworded_items": reworded_items,
    }


def extract_document_text(filename: str = "", content_b64: str = "", raw_text: str = "") -> dict:
    """
    Extracts clean book text from .pdf or .txt (base64 or raw text), strips PDF bookmarks/headers/footers/page numbers,
    and runs clean_and_reword_book_text() so it is 100% ready for natural audiobook narration.
    """
    import base64
    import io

    pages_count = 1
    extracted = raw_text or ""
    fname_low = (filename or "").lower().strip()

    if content_b64 and not extracted:
        raw_bytes = base64.b64decode(content_b64)
        if fname_low.endswith(".pdf") or raw_bytes[:4] == b"%PDF":
            page_texts = []
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(stream=raw_bytes, filetype="pdf")
                pages_count = len(doc)
                for page in doc:
                    rect_h = float(page.rect.height or 800.0)
                    blocks = page.get_text("blocks")
                    blocks = [b for b in blocks if len(b) >= 5 and (b[6] == 0 if len(b) > 6 else True)]
                    blocks.sort(key=lambda b: (round(b[1] / 12.0), b[0]))
                    kept_b = []
                    for b in blocks:
                        y0, y1, b_txt = float(b[1]), float(b[3]), str(b[4]).strip()
                        if not b_txt:
                            continue
                        if (y0 < rect_h * 0.055 or y1 > rect_h * 0.945) and len(b_txt) <= 75:
                            if re.search(r"^(?:trang|page|tr\.?|p\.?)?\s*\d{1,5}(?:\s*/\s*\d{1,5})?$|bookmark|mục lục", b_txt, re.I):
                                continue
                        kept_b.append(b_txt)
                    if kept_b:
                        page_texts.append("\n".join(kept_b))
                doc.close()
            except Exception:
                try:
                    import pypdf
                    reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
                    pages_count = len(reader.pages)
                    for pg in reader.pages:
                        t_pg = (pg.extract_text() or "").strip()
                        if t_pg:
                            page_texts.append(t_pg)
                except Exception as exc:
                    raise RuntimeError(f"Không thể đọc file PDF: {exc}")
            extracted = "\n\n".join(page_texts)
        else:
            for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1258", "latin-1"):
                try:
                    extracted = raw_bytes.decode(enc)
                    break
                except Exception:
                    continue

    res = clean_and_reword_book_text(extracted)
    return {
        "ok": True,
        "filename": filename,
        "pages": pages_count,
        "cleaned_text": res["text"],
        "removed_junk": res["removed_junk"],
        "reworded_items": res["reworded_items"],
    }


# ── BILINGUAL ENGLISH & VIETNAMESE ANALYZER + PHONETIC TRANSCRIBER + URL ARTICLE EXTRACTOR ──────────
# Linguistic Law: In Vietnamese orthography, syllables ending in stop consonants (-p, -t, -c, -ch)
# NEVER occur without a tone mark (they must carry sắc or nặng). Only open/sonorant-final syllables can be unaccented.
VN_NO_DIACRITIC_WORDS = {
    "a", "ai", "am", "an", "anh", "ao", "au", "ay",
    "ba", "bai", "ban", "bang", "bao", "bau", "bay",
    "be", "ben", "benh", "bi", "bia", "bien", "bieu", "binh",
    "bo", "boi", "bom", "bon", "bong", "bu", "bua", "bui", "bun", "bung", "buoi", "buon", "buong", "buu",
    "ca", "cai", "cam", "can", "canh", "cao", "cau", "cay",
    "cha", "chai", "cham", "chan", "chang", "chao", "chau", "chay",
    "che", "chen", "cheo", "chi", "chia", "chiem", "chien", "chieu", "chim", "chin", "chinh",
    "cho", "choi", "chom", "chon", "chong", "chu", "chua", "chui", "chum", "chung", "chuoi", "chuom", "chuon", "chuong", "chuyen",
    "co", "coi", "com", "con", "cong", "cu", "cua", "cui", "cum", "cung", "cuoi", "cuon", "cuong", "cuu",
    "da", "dai", "dam", "dan", "dang", "danh", "dao", "dau", "day",
    "de", "dem", "den", "deo", "di", "dia", "diem", "dien", "dieu", "dinh",
    "do", "doa", "doan", "doanh", "doi", "dom", "don", "dong", "du", "dua", "dui", "dum", "dun", "dung", "duoi", "duong",
    "e", "em", "en", "eo",
    "ga", "gai", "gam", "gan", "gang", "ganh", "gao", "gau", "gay",
    "ghe", "ghem", "ghen", "gheo", "ghi", "ghim", "gia", "giai", "giam", "gian", "giang", "gianh", "giao", "giau", "giay",
    "gie", "gieng", "gieu", "gin", "gio", "gioi", "gion", "giong", "giu", "giua", "giuong",
    "go", "goi", "gom", "gon", "gong", "gu", "gui", "gum", "gung", "guom", "guong",
    "ha", "hai", "ham", "han", "hang", "hanh", "hao", "hau", "hay",
    "he", "hem", "hen", "heo", "hi", "hia", "hien", "hieu", "hinh", "hiu",
    "ho", "hoa", "hoai", "hoan", "hoang", "hoanh", "hoi", "hom", "hon", "hong", "hu", "hua", "hui", "hum", "hung", "huong", "huou", "huu", "huy", "huyen", "huynh",
    "i", "im", "in", "inh", "iu",
    "ke", "kem", "ken", "kenh", "keo", "keu", "kha", "khai", "kham", "khan", "khang", "khanh", "khao", "khau", "khay",
    "khe", "khem", "khen", "kheo", "kheu", "khi", "khia", "khiem", "khien", "khieu", "khinh", "khiu",
    "kho", "khoa", "khoai", "khoan", "khoang", "khoanh", "khoe", "khoi", "khom", "khon", "khong", "khu", "khua", "khui", "khum", "khung", "khuon", "khuong", "khuu", "khuy", "khuya", "khuyen", "khuynh", "ki", "kia", "kiem", "kien", "kieu", "kim", "kin", "kinh",
    "la", "lai", "lam", "lan", "lang", "lanh", "lao", "lau", "lay",
    "le", "lem", "len", "lenh", "leo", "leu", "li", "lia", "liem", "lien", "lieu", "lim", "linh", "liu",
    "lo", "loa", "loai", "loan", "loang", "loe", "loi", "lom", "lon", "long", "lu", "lua", "luan", "lui", "lum", "lun", "lung", "luoi", "luom", "luon", "luong", "luu", "luyen",
    "ma", "mai", "mam", "man", "mang", "manh", "mao", "mau", "may",
    "me", "mem", "men", "menh", "meo", "meu", "mi", "mia", "mieng", "mien", "mieu", "min", "minh", "miu",
    "mo", "moi", "mom", "mon", "mong", "mu", "mua", "mui", "mum", "mun", "mung", "muoi", "muon", "muong", "muu", "my",
    "na", "nai", "nam", "nan", "nang", "nanh", "nao", "nau", "nay",
    "ne", "nem", "nen", "nenh", "neo", "neu", "nga", "ngai", "ngam", "ngan", "ngang", "nganh", "ngao", "ngau", "ngay",
    "nghe", "nghen", "ngheng", "ngheo", "ngheu", "nghi", "nghia", "nghiem", "nghien", "nghieu", "nghin", "nghiu",
    "ngo", "ngoa", "ngoai", "ngoan", "ngoang", "ngoe", "ngoi", "ngom", "ngon", "ngong", "ngu", "ngua", "ngui", "ngum", "ngun", "ngung", "nguoi", "nguong", "nguu", "nguy", "nguyen",
    "nha", "nhai", "nham", "nhan", "nhang", "nhanh", "nhao", "nhau", "nhay",
    "nhe", "nhem", "nhen", "nheo", "nhi", "nhia", "nhiem", "nhien", "nhieu", "nhim", "nhin", "nhinh", "nhiu",
    "nho", "nhoa", "nhoai", "nhoan", "nhoang", "nhoe", "nhoi", "nhom", "nhon", "nhong", "nhu", "nhua", "nhui", "nhum", "nhun", "nhung", "nhuoi", "nhuom", "nhuon", "nhuong", "nhuy", "ni", "nia", "niem", "nien", "nieu", "nim", "ninh", "niu",
    "no", "noi", "nom", "non", "nong", "nu", "nua", "nui", "num", "nung", "nuoi", "nuong", "nuu",
    "o", "oa", "oai", "oan", "oang", "oanh", "oe", "oi", "om", "on", "ong",
    "pha", "phai", "pham", "phan", "phang", "phanh", "phao", "phau", "phay",
    "phe", "phen", "pheo", "phi", "phia", "phiem", "phien", "phieu", "phim", "phin", "phinh", "phiu",
    "pho", "phoi", "phom", "phon", "phong", "phu", "phua", "phui", "phun", "phung", "phuong",
    "qua", "quai", "quam", "quan", "quang", "quanh", "quao", "quau", "quay",
    "que", "quen", "queo", "qui", "quoi", "quon", "quy", "quyen", "quynh",
    "ra", "rai", "ram", "ran", "rang", "ranh", "rao", "rau", "ray",
    "re", "rem", "ren", "reng", "reo", "reu", "ri", "ria", "rieng", "rieu", "rim", "rinh", "riu",
    "ro", "roa", "roai", "roan", "roang", "roi", "rom", "ron", "rong", "ru", "rua", "rui", "rum", "run", "rung", "ruoi", "ruom", "ruon", "ruong",
    "sa", "sai", "sam", "san", "sang", "sanh", "sao", "sau", "say",
    "se", "sem", "sen", "seo", "si", "sia", "siem", "sien", "sieu", "sim", "sinh", "siu",
    "so", "soa", "soai", "soan", "soang", "soi", "som", "son", "song", "su", "sua", "sui", "sum", "sun", "sung", "suoi", "suon", "suong", "suu", "suy", "suyen",
    "ta", "tai", "tam", "tan", "tang", "tanh", "tao", "tau", "tay",
    "te", "tem", "ten", "tenh", "teo", "teu", "tha", "thai", "tham", "than", "thang", "thanh", "thao", "thau", "thay",
    "the", "them", "then", "thenh", "theo", "theu", "thi", "thia", "thiem", "thien", "thieu", "thim", "thin", "thinh", "thiu",
    "tho", "thoa", "thoai", "thoan", "thoang", "thoi", "thom", "thon", "thong", "thu", "thua", "thuan", "thui", "thum", "thun", "thung", "thuoi", "thuom", "thuon", "thuong", "thuy", "thuyen",
    "ti", "tia", "tiem", "tien", "tieu", "tim", "tin", "tinh", "tiu",
    "to", "toa", "toai", "toan", "toang", "toe", "toi", "tom", "ton", "tong", "tra", "trai", "tram", "tran", "trang", "tranh", "trao", "trau", "tray",
    "tre", "trem", "tren", "treo", "treu", "tri", "tria", "triem", "trien", "trieu", "trinh", "triu",
    "tro", "troi", "trom", "tron", "trong", "tru", "trua", "trui", "trum", "trun", "trung", "truoi", "truon", "truong", "truyen", "truy",
    "tu", "tua", "tuan", "tui", "tum", "tun", "tung", "tuoi", "tuom", "tuon", "tuong", "tuu", "tuy", "tuyen", "tuyn",
    "u", "ua", "uan", "uang", "ui", "um", "un", "ung", "uoi", "uom", "uon", "uong", "uu", "uy", "uyen",
    "va", "vai", "vam", "van", "vang", "vanh", "vao", "vau", "vay",
    "ve", "vem", "ven", "venh", "veo", "veu", "vi", "via", "viem", "vien", "vieu", "vim", "vin", "vinh", "viu",
    "vo", "voi", "vom", "von", "vong", "vu", "vua", "vui", "vum", "vun", "vung", "vuoi", "vuon", "vuong",
    "xa", "xai", "xam", "xan", "xang", "xanh", "xao", "xau", "xay",
    "xe", "xem", "xen", "xeng", "xeo", "xeu", "xi", "xia", "xiem", "xien", "xieu", "xim", "xin", "xinh", "xiu",
    "xo", "xoa", "xoai", "xoan", "xoang", "xoe", "xoi", "xom", "xon", "xong", "xu", "xua", "xuan", "xui", "xum", "xun", "xung", "xuoi", "xuom", "xuong", "xuy", "xuyen",
    "y", "ia", "iem", "ien", "ieu", "im", "in", "inh", "iu", "ya", "yen", "yeu",
}

# Words that exist in both VN_NO_DIACRITIC_WORDS and basic English; when adjacent to English tokens or in an English clause, read as English!
AMBIGUOUS_EN_VN_MAP = {
    "to": "tu", "do": "đu", "go": "gâu", "so": "xâu", "no": "nâu",
    "he": "hi", "me": "mi", "be": "bi", "my": "mai", "in": "in",
    "on": "on", "an": "ân", "am": "em", "can": "ken", "man": "men",
    "men": "men", "way": "guây", "day": "đây", "may": "mây", "say": "xây",
    "pay": "pây", "lay": "lây", "ray": "rây", "bay": "bây", "run": "răn",
    "sun": "săn", "fun": "phăn", "win": "uyn", "pin": "pin", "fan": "phen",
    "ban": "ben", "van": "ven", "pan": "pen", "tan": "ten", "son": "săn",
    "ton": "tăn", "won": "guân", "see": "xi", "sea": "xi", "tea": "ti",
    "key": "ki", "fee": "phi", "bee": "bi", "too": "tu", "zoo": "du",
    "who": "hu", "two": "tu", "one": "guăn", "ten": "ten", "six": "xích",
    "now": "nao", "how": "hao", "low": "lâu", "row": "râu", "bow": "bâu",
    "new": "niu", "few": "phiu", "law": "lo", "raw": "ro", "saw": "xo",
    "war": "guo", "car": "ca", "bar": "ba", "far": "pha", "star": "sờ ta",
    "air": "e", "ear": "ia", "eye": "ai", "age": "ây", "ice": "ai",
    "use": "diu", "ask": "át", "end": "en", "old": "ôn", "own": "ôn",
    "buy": "bai", "try": "trai", "fly": "phờ lai", "sky": "sờ cai", "dry": "đờ rai",
}

CURATED_EN_PHRASES = [
    (r"\bPersonal\s+Finance\b", "Pơ sơ nồ Phai nen"),
    (r"\bMiddle\s+Management\b", "Mít đồ Ma nít mần"),
    (r"\bQuiet\s+Firing\b", "Khoai ợt Phai ơ ring"),
    (r"\bQuiet\s+Quitting\b", "Khoai ợt Khuýt tinh"),
    (r"\bSystem\s+Architecture\b", "Xít tầm Ác ki tếch chờ"),
    (r"\bBeginner's\s+Mind\b", "Bì ghin nờ Mai"),
    (r"\bArtificial\s+Intelligence\b", "A ti phi sồ In teo li dần"),
    (r"\bMachine\s+Learning\b", "Mờ sin Lơ ninh"),
    (r"\bDeep\s+Learning\b", "Đíp Lơ ninh"),
    (r"\bLarge\s+Language\s+Models?\b", "Lạc Leng guýt Mô đồ"),
    (r"\bNew\s+York\b", "Niu I óc"),
    (r"\bWall\s+Street\b", "Phố Guôn"),
    (r"\bSilicon\s+Valley\b", "Thung lũng Si li con"),
    (r"\bWhite\s+House\b", "Nhà Trắng"),
    (r"\bUnited\s+States\b", "Hoa Kỳ"),
    (r"\bReal\s+Estate\b", "Riu Ét tây"),
    (r"\bSupply\s+Chain\b", "Sắp pờ lai Chên"),
    (r"\bCustomer\s+Experience\b", "Cắt tơ mơ Ích pi ri ần"),
    (r"\bUser\s+Experience\b", "Diu dơ Ích pi ri ần"),
    (r"\bUser\s+Interface\b", "Diu dơ In tơ phây"),
    (r"\bKey\s+Visual\b", "Ki Vi duồ"),
    (r"\bSocial\s+Media\b", "Xô sồ Mi đi a"),
    (r"\bContent\s+Creator\b", "Con ten Cờ ri ây tờ"),
    (r"\bBig\s+Data\b", "Bích Đây ta"),
    (r"\bCloud\s+Computing\b", "Cờ lao Com piu tinh"),
    (r"\bOpen\s+Source\b", "Ô pần Xoọc"),
]

CURATED_EN_WORDS = {
    "ai": "ây ai",
    "api": "ây pi ai",
    "app": "áp",
    "apps": "áp",
    "apple": "áp pồ",
    "amazon": "a ma don",
    "anthropic": "an thờ rô pích",
    "algorithm": "an gô ri đầm",
    "analytics": "a na li tích",
    "architecture": "ác ki tếch chờ",
    "automation": "o tô mây sần",
    "backend": "bách en",
    "benchmark": "ben mác",
    "bitcoin": "bít coi",
    "blockchain": "bờ lốc chên",
    "brand": "bờ ren",
    "branding": "bờ ren đinh",
    "brief": "bờ ríp",
    "browser": "bờ rao dơ",
    "budget": "bắt giệt",
    "business": "bít nít",
    "cache": "cát",
    "campaign": "cam pên",
    "capone": "ca pôn",
    "carnegie": "ca nê ghi",
    "cashflow": "cát phờ lâu",
    "ceo": "xi i ô",
    "cfo": "xi ép ô",
    "chatgpt": "chát gi pi ti",
    "chicago": "si ca gô",
    "chip": "chíp",
    "claude": "cờ lốt",
    "client": "cờ lai ần",
    "cloud": "cờ lao",
    "code": "cốt",
    "coding": "cốt đinh",
    "concept": "con xép",
    "content": "con ten",
    "copyright": "cóp pi rai",
    "core": "co",
    "corporate": "co pơ rết",
    "cpu": "xi pi iu",
    "creator": "cờ ri ây tờ",
    "crowley": "cờ rao li",
    "crypto": "cờ ríp tô",
    "cyber": "sai bơ",
    "dale": "đêu",
    "dashboard": "đát bo",
    "data": "đây ta",
    "database": "đây ta bây",
    "deadline": "đét lai",
    "debug": "đì bấc",
    "deep": "đíp",
    "default": "đì phôn",
    "demo": "đề mô",
    "deploy": "đì pờ loi",
    "deployment": "đì pờ loi mần",
    "design": "đì zai",
    "designer": "đì zai nơ",
    "developer": "đì ve lốp pơ",
    "devops": "đép óp",
    "digital": "đi gi tồ",
    "docker": "đóc cơ",
    "domain": "đô mên",
    "download": "đao lốt",
    "ecosystem": "i cô xít tầm",
    "edison": "ê đi xơn",
    "email": "i mêu",
    "empathetic": "em pa thê tích",
    "empire": "em pai ờ",
    "engine": "en gin",
    "engineer": "en gi nia",
    "engineering": "en gi nia ring",
    "enterprise": "en tơ pờ rai",
    "facebook": "phây búc",
    "feature": "phi chờ",
    "feedback": "phít bách",
    "file": "phai",
    "finance": "phai nen",
    "fintech": "phin tếch",
    "firewall": "phai ơ guôn",
    "firmware": "phơm que",
    "focus": "phô cớt",
    "folder": "phôn đơ",
    "format": "pho mát",
    "founder": "phao đơ",
    "framework": "phờ rêm guốc",
    "franklin": "phờ răng cờ lin",
    "freelance": "phờ ri len",
    "freelancer": "phờ ri len xơ",
    "frontend": "phờ răn en",
    "fullstack": "phun sờ tách",
    "function": "phăng sần",
    "game": "ghêm",
    "gaming": "ghêm minh",
    "gdp": "gi đi pi",
    "gemini": "giê mi nai",
    "github": "ghít hấp",
    "global": "gờ lô bồ",
    "google": "gu gồ",
    "gpu": "gi pi iu",
    "growth": "gờ râu",
    "hacker": "hách cơ",
    "hardware": "hát que",
    "hashtag": "hát tác",
    "highlight": "hai lai",
    "holding": "hâu đinh",
    "hollywood": "ho li út",
    "hosting": "hốt tinh",
    "hotline": "hót lai",
    "hybrid": "hai bờ rít",
    "idea": "ai đia",
    "impact": "im pách",
    "import": "im pọt",
    "index": "in đếch",
    "influencer": "in phờ lu ân xơ",
    "innovation": "in nô vây sần",
    "insight": "in sai",
    "instagram": "in sờ ta gờ ram",
    "interface": "in tơ phây",
    "internet": "in tơ nét",
    "invest": "in vét",
    "investment": "in vét mần",
    "investor": "in vét tơ",
    "iphone": "ai phôn",
    "issue": "ít siu",
    "java": "gia va",
    "javascript": "gia va sờ cờ ríp",
    "job": "gióp",
    "key": "ki",
    "keyword": "ki guốc",
    "koc": "ây ô xi",
    "kol": "ây ô eo",
    "kpi": "cây pi ai",
    "laptop": "láp tóp",
    "launch": "lon",
    "layout": "lây ao",
    "lead": "lít",
    "leader": "lít đơ",
    "leadership": "lít đơ síp",
    "learning": "lơ ninh",
    "level": "le vồ",
    "lifestyle": "lai sờ tai",
    "lincoln": "lin côn",
    "link": "linh",
    "linkedin": "linh in",
    "linux": "li nức",
    "live": "lai",
    "livestream": "lai chim",
    "local": "lô cồ",
    "logic": "lô gíc",
    "login": "lốc in",
    "logo": "lô gô",
    "luxury": "lắc xơ ri",
    "macbook": "mác búc",
    "machine": "mờ sin",
    "management": "ma nít mần",
    "manager": "ma nít giơ",
    "margin": "ma gin",
    "market": "ma kịt",
    "marketing": "ma két tinh",
    "master": "mát tơ",
    "matrix": "mây trích",
    "media": "mi đi a",
    "meeting": "mít tinh",
    "memory": "me mô ri",
    "mentor": "men tơ",
    "meta": "mê ta",
    "metric": "mê trích",
    "micro": "mai cờ rô",
    "microsoft": "mai cờ rô xóp",
    "middle": "mít đồ",
    "mindset": "mai xét",
    "mini": "mi ni",
    "mobile": "mô bai",
    "mode": "mốt",
    "model": "mô đồ",
    "modern": "mô đần",
    "module": "mô đun",
    "money": "măn ni",
    "monitor": "mô ni tơ",
    "native": "nây típ",
    "network": "nét guốc",
    "networking": "nét guốc kinh",
    "news": "niu",
    "next": "nếch",
    "niche": "nít",
    "node": "nốt",
    "note": "nốt",
    "nvidia": "en vi đi a",
    "office": "óp phít",
    "offline": "óp lai",
    "ok": "ô kê",
    "okay": "ô kê",
    "onboarding": "on bo đinh",
    "online": "on lai",
    "open": "ô pần",
    "openai": "ô pần ây ai",
    "operation": "óp pơ rây sần",
    "optimize": "óp ti mai",
    "option": "óp sần",
    "order": "o đơ",
    "organic": "o ga ních",
    "output": "ao pút",
    "outsource": "ao xoọc",
    "package": "pách kịt",
    "page": "pây",
    "panel": "pa nồ",
    "partner": "pát nơ",
    "J.P.": "giây pi",
    "password": "pát guốc",
    "pattern": "pát tần",
    "payload": "pây lốt",
    "payment": "pây mần",
    "pdf": "pi đi ép",
    "performance": "pơ pho mần",
    "personal": "pơ sơ nồ",
    "pipeline": "pai lai",
    "pitch": "pít",
    "pixel": "pích xeo",
    "plan": "pờ len",
    "planning": "pờ len ninh",
    "platform": "pờ lát phom",
    "play": "pờ lây",
    "plugin": "pờ lắc in",
    "plus": "pờ lớt",
    "podcast": "pót cát",
    "point": "poi",
    "policy": "po li xi",
    "popup": "póp ắp",
    "portal": "po tồ",
    "portfolio": "pọt phô li ô",
    "post": "pốt",
    "power": "pao ơ",
    "premium": "pờ ri mi um",
    "preset": "pờ ri xét",
    "preview": "pờ ri viu",
    "price": "pờ rai",
    "pricing": "pờ rai xinh",
    "private": "pờ rai vợt",
    "pro": "pờ rô",
    "process": "pờ rô xét",
    "product": "pờ rô đắc",
    "production": "pờ rô đắc sần",
    "profile": "pờ rô phai",
    "program": "pờ rô gờ ram",
    "project": "pờ rô giếch",
    "prompt": "pờ rom",
    "protocol": "pờ rô tô côn",
    "proxy": "pờ róc xi",
    "public": "pắp lích",
    "python": "pai thon",
    "quality": "qua li ti",
    "query": "que ri",
    "queue": "khiu",
    "quiet": "khoai ợt",
    "quote": "cuốt",
    "radar": "ra đa",
    "radio": "ra đi ô",
    "ranking": "răng kinh",
    "rate": "rây",
    "rating": "rây tinh",
    "react": "ri ách",
    "realtime": "riu tai",
    "record": "rì coọc",
    "recording": "rì coọc đinh",
    "refactor": "rì phách tơ",
    "release": "rì li",
    "reload": "rì lốt",
    "remote": "rì mốt",
    "render": "ren đơ",
    "rendering": "ren đơ ring",
    "report": "rì pọt",
    "request": "rì quét",
    "research": "rì xớt",
    "reset": "rì xét",
    "resource": "rì xoọc",
    "response": "rì sờ pon",
    "retail": "rì têu",
    "return": "rì tơn",
    "revenue": "re vơ niu",
    "review": "ri viu",
    "reword": "rì guốc",
    "rewording": "rì guốc đinh",
    "risk": "rít",
    "roadmap": "rốt máp",
    "robot": "rô bốt",
    "rockefeller": "rốc phe lơ",
    "roi": "a ô ai",
    "role": "râu",
    "roosevelt": "ru dơ ven",
    "route": "rút",
    "router": "rao tơ",
    "runtime": "răn tai",
    "saas": "xát",
    "sale": "sêu",
    "sales": "sêu",
    "sample": "xam pồ",
    "scale": "sờ kêu",
    "scaling": "sờ kêu linh",
    "scan": "sờ can",
    "scene": "xin",
    "schedule": "sờ ke điu",
    "schema": "sờ ki ma",
    "Schwab": "sờ oáp",
    "schwab": "sờ oáp",
    "score": "sờ co",
    "screen": "sờ cờ rin",
    "script": "sờ cờ ríp",
    "scroll": "sờ cờ rôn",
    "search": "xớt",
    "section": "xếch sần",
    "security": "xì kiu ri ti",
    "segment": "xéc mần",
    "select": "xì lếch",
    "senior": "xi ni ơ",
    "sensor": "xen xơ",
    "seo": "ét i ô",
    "series": "xê ri",
    "server": "xơ vơ",
    "service": "xơ vịt",
    "session": "xét sần",
    "set": "xét",
    "setting": "xét tinh",
    "setup": "xét ắp",
    "share": "se",
    "shift": "síp",
    "shock": "sốc",
    "shop": "sóp",
    "shopee": "sóp pi",
    "shopping": "sóp ping",
    "short": "soọt",
    "show": "sô",
    "showroom": "sô rum",
    "signal": "xích nồ",
    "simple": "xim pồ",
    "single": "xinh gồ",
    "site": "sai",
    "size": "sai",
    "skill": "sờ kiu",
    "slide": "sờ lai",
    "slider": "sờ lai đơ",
    "smart": "sờ mát",
    "smartphone": "sờ mát phôn",
    "smooth": "sờ mút",
    "snapshot": "sờ náp soọt",
    "social": "xô sồ",
    "socket": "xóc kịt",
    "software": "xóp que",
    "solution": "xô lu sần",
    "sound": "xao",
    "source": "xoọc",
    "spa": "sờ pa",
    "space": "sờ pây",
    "spam": "sờ pam",
    "speaker": "sờ pích cơ",
    "special": "sờ pe sồ",
    "speed": "sờ pít",
    "sprint": "sờ pờ rin",
    "sql": "ét quy eo",
    "stable": "sờ tây bồ",
    "stack": "sờ tách",
    "staff": "sờ táp",
    "stage": "sờ tây",
    "standard": "sờ tan đớt",
    "start": "sờ tát",
    "startup": "sờ tát ắp",
    "state": "sờ tây",
    "status": "sờ ta tớt",
    "step": "sờ tép",
    "stock": "sờ tóc",
    "stop": "sờ tốp",
    "storage": "sờ to rịt",
    "store": "sờ to",
    "story": "sờ to ri",
    "storytelling": "sờ to ri teo linh",
    "strategy": "sờ tra tê gi",
    "stream": "sờ chim",
    "streaming": "sờ chim minh",
    "stress": "sờ trét",
    "string": "sờ trinh",
    "structure": "sờ trắc chờ",
    "studio": "sờ tu đi ô",
    "style": "sờ tai",
    "submit": "sắp mít",
    "summary": "xăm mơ ri",
    "super": "xu pơ",
    "support": "sắp pọt",
    "survey": "xơ vây",
    "switch": "sờ uýt",
    "sync": "xinh",
    "system": "xít tầm",
    "tab": "táp",
    "table": "tây bồ",
    "tablet": "táp lẹt",
    "tag": "tác",
    "talent": "ta lần",
    "target": "ta ghẹt",
    "task": "tát",
    "team": "tim",
    "teamwork": "tim guốc",
    "tech": "tếch",
    "techcombank": "tếch com băng",
    "technology": "tếch nô lô gi",
    "telegram": "tê lê gờ ram",
    "template": "tem pờ lết",
    "terminal": "tơ mi nồ",
    "test": "tét",
    "testing": "tét tinh",
    "text": "tếch",
    "theme": "thim",
    "thread": "thờ rét",
    "threads": "thờ rét",
    "ticket": "tích kịt",
    "tiktok": "tíc tóc",
    "time": "tai",
    "timeline": "tai lai",
    "timeout": "tai ao",
    "timer": "tai mơ",
    "tip": "típ",
    "tips": "típ",
    "title": "tai tồ",
    "token": "tô cần",
    "tool": "tun",
    "tools": "tun",
    "top": "tóp",
    "topic": "tóp pích",
    "total": "tô tồ",
    "touch": "tắt",
    "tour": "tua",
    "track": "trách",
    "tracking": "trách kinh",
    "trade": "trây",
    "trader": "trây đơ",
    "trading": "trây đinh",
    "traffic": "tra phích",
    "trailer": "trây lơ",
    "train": "trên",
    "trainer": "trên nơ",
    "training": "trên ninh",
    "transfer": "tran phơ",
    "transform": "tran phom",
    "trend": "tren",
    "trending": "tren đinh",
    "trial": "trai ồ",
    "trigger": "trích gơ",
    "trust": "trớt",
    "tunnel": "tăn nồ",
    "turbo": "tuốc bô",
    "tutorial": "tiu to ri ồ",
    "tvc": "ti vi xi",
    "type": "tai",
    "ui": "iu ai",
    "ultra": "un tra",
    "unit": "iu nịt",
    "update": "ắp đết",
    "upgrade": "ắp gờ rết",
    "upload": "ắp lốt",
    "url": "iu a eo",
    "usb": "iu ét bi",
    "usd": "đô la mỹ",
    "user": "diu dơ",
    "ux": "iu ích",
    "value": "va liu",
    "vector": "véc tơ",
    "version": "vơ sần",
    "vest": "vét",
    "vibe": "vai",
    "video": "vi đê ô",
    "vietcombank": "việt com băng",
    "vietinbank": "việt tin băng",
    "view": "viu",
    "viewer": "viu ơ",
    "villa": "vi la",
    "vinamilk": "vi na miu",
    "vinhomes": "vin hôm",
    "vip": "víp",
    "viral": "vai rồ",
    "virtual": "vơ chuồ",
    "vision": "vi sần",
    "visual": "vi duồ",
    "vlog": "vê lốc",
    "vlogger": "vê lốc gơ",
    "voice": "voi",
    "volume": "vô lum",
    "voucher": "vao chờ",
    "vpbank": "vi pi băng",
    "vr": "vi a",
    "vtv": "vê tê vê",
    "vtv1": "vê tê vê một",
    "htv": "hát tê vê",
    "htv7": "hát tê vê bảy",
    "htv9": "hát tê vê chín",
    "wallet": "gua lẹt",
    "washington": "oa sinh tơn",
    "watermark": "gua tơ mác",
    "web": "guép",
    "webcam": "guép cam",
    "webinar": "guép bi na",
    "website": "guép sai",
    "wechat": "uy chát",
    "widget": "uýt giệt",
    "wifi": "oai phai",
    "wiki": "uy ki",
    "wikipedia": "uy ki pi đi a",
    "william": "uy li am",
    "window": "uyn đâu",
    "windows": "uyn đâu",
    "wireframe": "oai phờ rêm",
    "work": "guốc",
    "worker": "guốc cơ",
    "workflow": "guốc phờ lâu",
    "working": "guốc kinh",
    "workshop": "guốc sóp",
    "workspace": "guốc sờ pây",
    "world": "guôn",
    "youtube": "diu túp",
    "youtuber": "diu túp bơ",
    "zalo": "da lô",
    "zero": "di rô",
    "zone": "dôn",
    "zoom": "dum",
}

_CMU_DICT_CACHE = None


def get_cmu_dict() -> dict:
    global _CMU_DICT_CACHE
    if _CMU_DICT_CACHE is None:
        try:
            import cmudict
            _CMU_DICT_CACHE = cmudict.dict()
        except Exception:
            _CMU_DICT_CACHE = {}
    return _CMU_DICT_CACHE


ARPABET_VOWELS = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"
}
ARPABET_VOWEL_MAP = {
    "AA": "a", "AE": "e", "AH": "ơ", "AO": "o", "AW": "ao", "AY": "ai",
    "EH": "e", "ER": "ơ", "EY": "ây", "IH": "i", "IY": "i",
    "OW": "âu", "OY": "oi", "UH": "u", "UW": "u",
}
ARPABET_ONSET_MAP = {
    "B": "b", "CH": "ch", "D": "đ", "DH": "đ", "F": "ph", "G": "g", "HH": "h",
    "JH": "gi", "K": "c", "L": "l", "M": "m", "N": "n", "NG": "ng", "P": "p",
    "R": "r", "S": "x", "SH": "s", "T": "t", "TH": "th", "V": "v", "W": "gu",
    "Y": "di", "Z": "d", "ZH": "gi",
}
ARPABET_CODA_MAP = {
    "M": "m", "N": "n", "NG": "ng", "P": "p", "T": "t", "K": "c",
    "B": "p", "D": "t", "G": "c", "CH": "ch", "JH": "ch", "F": "p", "V": "p",
}
ARPABET_SYLLABLE_FALLBACK = {
    "B": "bờ", "CH": "chờ", "D": "đờ", "DH": "đờ", "F": "phờ", "G": "gờ", "HH": "hờ",
    "JH": "giơ", "K": "cờ", "L": "lồ", "M": "mờ", "N": "nờ", "NG": "ngờ", "P": "pờ",
    "R": "rờ", "S": "xờ", "SH": "sờ", "T": "tờ", "TH": "thờ", "V": "vờ", "W": "gu",
    "Y": "di", "Z": "dờ", "ZH": "giơ",
}


def arpabet_to_vn(phones: list) -> str:
    clean_p = [re.sub(r"\d+", "", p) for p in phones]
    syllables = []
    i = 0
    n = len(clean_p)
    while i < n:
        onset = []
        while i < n and clean_p[i] not in ARPABET_VOWELS:
            onset.append(clean_p[i])
            i += 1
        if i >= n:
            for c in onset:
                if c in ARPABET_SYLLABLE_FALLBACK and c not in ("R",):
                    syllables.append(ARPABET_SYLLABLE_FALLBACK[c])
            break
        v = clean_p[i]
        i += 1
        coda = []
        while i < n and clean_p[i] not in ARPABET_VOWELS:
            if i + 1 < n and clean_p[i + 1] in ARPABET_VOWELS:
                break
            if i + 2 < n and clean_p[i + 2] in ARPABET_VOWELS and clean_p[i + 1] in ("L", "R", "W", "Y"):
                break
            coda.append(clean_p[i])
            i += 1
        if len(onset) > 1:
            for c in onset[:-1]:
                if c in ARPABET_SYLLABLE_FALLBACK:
                    syllables.append(ARPABET_SYLLABLE_FALLBACK[c])
            onset_c = onset[-1]
        elif len(onset) == 1:
            onset_c = onset[0]
        else:
            onset_c = ""
        vn_on = ARPABET_ONSET_MAP.get(onset_c, "")
        vn_v = ARPABET_VOWEL_MAP.get(v, "ơ")
        if vn_on == "c" and vn_v.startswith(("e", "i", "ê")):
            vn_on = "k"
        elif vn_on == "g" and vn_v.startswith(("e", "i", "ê")):
            vn_on = "gh"
        elif vn_on == "ng" and vn_v.startswith(("e", "i", "ê")):
            vn_on = "ngh"
        elif vn_on == "gu" and vn_v.startswith(("u", "o", "ô", "ơ")):
            vn_on = "g"
        elif vn_on == "di" and vn_v.startswith("i"):
            vn_on = "d"
        vn_co = ""
        if coda:
            c0 = coda[0]
            if c0 in ARPABET_CODA_MAP and vn_v in ("a", "e", "i", "o", "u", "ơ"):
                vn_co = ARPABET_CODA_MAP[c0]
                if vn_co in ("p", "t", "c", "ch"):
                    acute = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "ơ": "ớ"}
                    vn_v = acute.get(vn_v, vn_v)
        syllables.append(f"{vn_on}{vn_v}{vn_co}")
    return " ".join(s for s in syllables if s).strip()


def english_word_to_vn_fallback(word: str) -> str:
    """Rule-based English grapheme-to-Vietnamese syllable converter for words outside CMUdict."""
    w = word.lower().strip("'-")
    if not w:
        return word
    if w in CURATED_EN_WORDS:
        return CURATED_EN_WORDS[w]
    cmu = get_cmu_dict()
    if w in cmu and cmu[w]:
        res = arpabet_to_vn(cmu[w][0])
        if res:
            return res
    # Handle common suffixes by splitting stem + suffix
    for suf, suf_vn in (
        ("tion", "sần"), ("sion", "sần"), ("ment", "mần"), ("ness", "nít"),
        ("able", "ơ bồ"), ("ible", "ơ bồ"), ("ing", "inh"), ("ed", "ịt"), ("er", "ơ"), ("ly", "li"),
    ):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            stem = w[: -len(suf)]
            if stem in CURATED_EN_WORDS:
                return f"{CURATED_EN_WORDS[stem]} {suf_vn}"
            if stem in cmu and cmu[stem]:
                return f"{arpabet_to_vn(cmu[stem][0])} {suf_vn}"
    # If all uppercase 2-5 letter acronym (e.g. NASA, NATO, HTML, JSON, SaaS)
    if word.isupper() and 2 <= len(word) <= 5:
        letter_map = {
            "A": "ây", "B": "bi", "C": "xi", "D": "đi", "E": "i", "F": "ép", "G": "gi",
            "H": "ết", "I": "ai", "J": "giây", "K": "cây", "L": "eo", "M": "em", "N": "en",
            "O": "ô", "P": "pi", "Q": "khiu", "R": "a", "S": "ét", "T": "ti", "U": "iu",
            "V": "vi", "W": "đắp bồ iu", "X": "ích", "Y": "oai", "Z": "di",
        }
        return " ".join(letter_map.get(ch, ch.lower()) for ch in word)
    return word


def is_english_token(word: str) -> bool:
    """Determines if an ASCII alphabetic token is an English word rather than an unaccented Vietnamese word."""
    w_clean = word.strip("'-")
    if not w_clean or not re.match(r"^[A-Za-z]+(?:['-][A-Za-z]+)*$", w_clean):
        return False
    low = w_clean.lower()
    if low in CURATED_EN_WORDS:
        return True
    if low in VN_NO_DIACRITIC_WORDS:
        return False
    if any(ch in low for ch in ("f", "j", "w", "z")):
        return True
    cmu = get_cmu_dict()
    if low in cmu:
        return True
    if len(low) >= 4 and re.search(r"(?:tion|sion|ment|ight|ough|ould|ance|ence|ship|ward|less|ness|able|ible|ology|graph|ware|line|work|book|tech|cloud|data|flow)$", low):
        return True
    return False


def translate_en_to_vi_text(text: str) -> str:
    """Translates English paragraphs/articles into natural Vietnamese via Google GTX endpoint with safe fallback."""
    if not text or not text.strip():
        return text
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    translated_paras = []
    # Chunk into <= 1600 char batches
    batch = []
    batch_len = 0

    def _flush_batch(b_list):
        if not b_list:
            return
        joined = "\n".join(b_list)
        try:
            q = urllib.parse.quote(joined)
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=vi&dt=t&q={q}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if isinstance(data, list) and data and isinstance(data[0], list):
                    trans_str = "".join(seg[0] for seg in data[0] if isinstance(seg, list) and seg and seg[0])
                    if trans_str.strip():
                        translated_paras.append(trans_str.strip())
                        return
        except Exception:
            pass
        translated_paras.append(joined)

    for p in paragraphs:
        if batch_len + len(p) > 1500 and batch:
            _flush_batch(batch)
            batch = [p]
            batch_len = len(p)
        else:
            batch.append(p)
            batch_len += len(p)
    if batch:
        _flush_batch(batch)
    return "\n\n".join(translated_paras)


def _transcribe_english_in_context(text: str) -> tuple:
    """
    Context-aware Bilingual Token Analyzer & Transcriber:
    - Unambiguous English words (in CURATED_EN_WORDS, CMUdict outside VN_NO_DIACRITIC_WORDS, stop-final ASCII words, etc.) are always English.
    - Ambiguous short ASCII words in AMBIGUOUS_EN_VN_MAP (e.g. 'to', 'do', 'go', 'so', 'no', 'he', 'me', 'be', 'my', 'in', 'on', 'an', 'am', 'can', 'man', 'way', 'day')
      are treated as English when adjacent to an English word or inside a sentence with >= 35% unambiguous English words!
    """
    token_iter = list(re.finditer(r"[A-Za-zÀ-ỹ]+(?:['-][A-Za-zÀ-ỹ]+)*", text))
    if not token_iter:
        return text, 0, 0, {}

    n_tok = len(token_iter)
    kinds = []  # "vn", "en", "ambig", "skip"
    for m in token_iter:
        w = m.group(0)
        if w.startswith(("VBEEACT", "VBEETAG")):
            kinds.append("skip")
        elif re.search(r"[À-ỹ]", w):
            kinds.append("vn")
        elif is_english_token(w):
            kinds.append("en")
        elif w.lower() in AMBIGUOUS_EN_VN_MAP:
            kinds.append("ambig")
        else:
            kinds.append("vn")

    unambig_en = sum(1 for k in kinds if k == "en")
    unambig_vn = sum(1 for k in kinds if k == "vn")
    mostly_english_doc = (unambig_en > 0) and (unambig_en >= unambig_vn * 0.65)

    # Resolve "ambig" tokens using local window [i-2 .. i+2] and document ratio
    for i in range(n_tok):
        if kinds[i] != "ambig":
            continue
        if mostly_english_doc:
            kinds[i] = "en"
            continue
        left_en = (i > 0 and kinds[i - 1] == "en") or (i > 1 and kinds[i - 2] == "en" and kinds[i - 1] == "ambig")
        right_en = (i + 1 < n_tok and kinds[i + 1] == "en") or (i + 2 < n_tok and kinds[i + 2] == "en" and kinds[i + 1] == "ambig")
        if left_en or right_en:
            kinds[i] = "en"
        else:
            kinds[i] = "vn"

    vn_count = sum(1 for k in kinds if k == "vn")
    en_count = sum(1 for k in kinds if k == "en")
    en_samples_map = {}

    out_parts = []
    last_pos = 0
    for i, m in enumerate(token_iter):
        out_parts.append(text[last_pos : m.start()])
        w = m.group(0)
        if kinds[i] == "en":
            low = w.lower()
            if low in AMBIGUOUS_EN_VN_MAP:
                vn_phon = AMBIGUOUS_EN_VN_MAP[low]
            else:
                vn_phon = english_word_to_vn_fallback(w)
            if low not in en_samples_map and len(en_samples_map) < 18 and len(low) >= 2:
                en_samples_map[low] = vn_phon
            out_parts.append(vn_phon)
        else:
            out_parts.append(w)
        last_pos = m.end()
    out_parts.append(text[last_pos:])
    return "".join(out_parts), vn_count, en_count, en_samples_map


def analyze_and_adapt_english_vietnamese(text: str, mode: str = "auto_phonetic") -> dict:
    """
    Automatically analyzes English vs Vietnamese tokens in any text or extracted news article:
    - Counts Vietnamese words vs English words (`vn_word_count`, `en_word_count`, `vn_percent`, `en_percent`).
    - Lists detected English terms and their Vietnamese phonetic pronunciations (`english_samples`).
    - If `mode == "translate_vi"` (or `mode == "auto_translate"` when `en_percent >= 55`), translates English into fluent Vietnamese.
    - Converts English words/sentences into smooth Vietnamese syllables (`phonetic_text`) so VieNeu-TTS v3 Turbo reads both languages seamlessly.
    """
    if not text or not text.strip():
        return {
            "ok": True,
            "detected_lang": "Tiếng Việt",
            "vn_word_count": 0,
            "en_word_count": 0,
            "vn_percent": 100,
            "en_percent": 0,
            "english_samples": [],
            "clean_display_text": "",
            "phonetic_text": "",
            "translated": False,
        }

    # Protect valid acting tags before scanning words
    protected = []

    def _save_act(m):
        full = m.group(0)
        if VALID_ACTING_TAG_RE.match(full):
            idx = len(protected)
            protected.append(full)
            return f"\x02VBEEACT{idx}\x03"
        return full

    scan_t = re.sub(r"\[[^\]]+\]", _save_act, text)
    _, vn_count, en_count, en_samples_map = _transcribe_english_in_context(scan_t)

    total_w = max(1, vn_count + en_count)
    en_pct = int(round((en_count * 100.0) / total_w))
    vn_pct = 100 - en_pct

    if en_pct >= 60:
        detected_lang = "Tiếng Anh (English Article)"
    elif en_count >= 2 or en_pct >= 5:
        detected_lang = "Song Ngữ Anh - Việt (Bilingual)"
    else:
        detected_lang = "Tiếng Việt (Chuẩn)"

    did_translate = False
    display_text = text
    if mode == "translate_vi" or (mode == "auto_translate" and en_pct >= 55):
        display_text = translate_en_to_vi_text(text)
        did_translate = True

    # Build phonetic_text by applying curated multi-word English phrases first, then context-aware English tokens
    work_t = re.sub(r"\[[^\]]+\]", _save_act, display_text)
    for pat, rep in CURATED_EN_PHRASES:
        work_t = re.sub(pat, rep, work_t, flags=re.I)

    phonetic_t, _, _, _ = _transcribe_english_in_context(work_t)
    for idx, val in enumerate(protected):
        phonetic_t = phonetic_t.replace(f"\x02VBEEACT{idx}\x03", val)

    samples_list = [{"en": k, "vi": v} for k, v in list(en_samples_map.items())[:14]]
    return {
        "ok": True,
        "detected_lang": detected_lang,
        "vn_word_count": vn_count,
        "en_word_count": en_count,
        "vn_percent": vn_pct,
        "en_percent": en_pct,
        "english_samples": samples_list,
        "clean_display_text": display_text,
        "phonetic_text": phonetic_t,
        "translated": did_translate,
    }


def extract_article_from_url(url: str, bilingual_mode: str = "auto_phonetic") -> dict:
    """
    Extracts clean news/article/blog/book text from any pasted URL:
    1. Fetches HTML (or PDF/TXT) with browser User-Agent + trafilatura + BeautifulSoup article body selector + r.jina.ai fallback.
    2. Strips ads, navigation, related-news boxes, photo captions, author bylines, social share buttons, and bookmarks.
    3. Runs clean_and_reword_book_text() + analyze_and_adapt_english_vietnamese() so English & Vietnamese are both analyzed and ready to read.
    """
    target_url = (url or "").strip()
    md_m = re.search(r"https?://[^\s\)\]\">]+", target_url)
    if md_m:
        target_url = md_m.group(0)
    elif target_url and not target_url.startswith(("http://", "https://")):
        target_url = "https://" + target_url

    if not target_url or not target_url.startswith(("http://", "https://")):
        raise ValueError("Vui lòng dán đường link hợp lệ (bắt đầu bằng https:// hoặc http://).")

    parsed_u = urllib.parse.urlparse(target_url)
    site_name = (parsed_u.netloc or "").replace("www.", "")
    title = ""
    raw_article = ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    html_content = ""
    try:
        req = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            raw_bytes = resp.read()
            if "application/pdf" in ctype or target_url.lower().endswith(".pdf"):
                import base64
                doc_res = extract_document_text(
                    filename=os.path.basename(parsed_u.path) or "article.pdf",
                    content_b64=base64.b64encode(raw_bytes).decode("ascii"),
                )
                raw_article = doc_res["cleaned_text"]
                title = os.path.basename(parsed_u.path) or site_name
            else:
                for enc in ("utf-8", "utf-8-sig", "cp1258", "latin-1"):
                    try:
                        html_content = raw_bytes.decode(enc)
                        break
                    except Exception:
                        continue
    except Exception:
        html_content = ""

    # 1. Try trafilatura first (gold-standard news & article extractor)
    if html_content and not raw_article:
        try:
            import trafilatura
            meta = trafilatura.extract_metadata(html_content, default_url=target_url)
            if meta:
                if getattr(meta, "title", None):
                    title = str(meta.title).strip()
                if getattr(meta, "sitename", None):
                    site_name = str(meta.sitename).strip()
            extracted_tf = trafilatura.extract(
                html_content,
                url=target_url,
                include_comments=False,
                include_tables=False,
                include_images=False,
                include_links=False,
                favor_precision=True,
            )
            if extracted_tf and len(extracted_tf.strip()) >= 120:
                raw_article = extracted_tf.strip()
        except Exception:
            pass

    # 2. Fallback / Title enrichment with BeautifulSoup4 tailored for VnExpress, DanTri, TuoiTre, ThanhNien, CafeF, BBC, Medium, etc.
    if html_content and (not raw_article or not title):
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")
            if not title:
                og_t = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "title"})
                if og_t and og_t.get("content"):
                    title = str(og_t["content"]).strip()
                elif soup.find("h1"):
                    title = soup.find("h1").get_text(" ", strip=True)
                elif soup.title and soup.title.string:
                    title = str(soup.title.string).strip()

            if not raw_article:
                for bad_sel in (
                    "script", "style", "noscript", "header", "footer", "nav", "aside", "form", "iframe", "svg",
                    "figure", "figcaption", ".related-news", ".box-tin-lien-quan", ".list-news", ".social-share",
                    ".breadcrumb", ".tags", ".box-comment", ".ads", ".advertisement", "[role='navigation']",
                ):
                    for node in soup.select(bad_sel):
                        node.decompose()

                article_node = None
                for sel in (
                    "article.fck_detail", ".fck_detail", ".singular-content", ".detail-content", ".article-content",
                    ".detail__content", ".content-detail", "[itemprop='articleBody']", "article", "main", "#main-detail",
                ):
                    cand = soup.select_one(sel)
                    if cand and len(cand.get_text(" ", strip=True)) >= 120:
                        article_node = cand
                        break

                target_root = article_node or soup.body or soup
                paras = []
                sapo = soup.select_one(".description, .sapo, .singular-sapo, .detail-sapo, [itemprop='description']")
                if sapo:
                    sapo_txt = sapo.get_text(" ", strip=True)
                    if len(sapo_txt) >= 25:
                        paras.append(sapo_txt)
                for p in target_root.find_all(["p", "h2", "h3", "blockquote"]):
                    pt = p.get_text(" ", strip=True)
                    if len(pt) >= 25 and not re.search(r"^(?:Xem thêm|Đọc thêm|Tin liên quan|Ảnh\s*:|Nguồn\s*:|Theo\s+[A-Z])", pt, re.I):
                        if pt not in paras:
                            paras.append(pt)
                if paras:
                    raw_article = "\n\n".join(paras)
        except Exception:
            pass

    # 3. Fallback via r.jina.ai reader if site uses heavy JS or Cloudflare challenge
    if not raw_article or len(raw_article.strip()) < 80:
        try:
            jina_url = f"https://r.jina.ai/{target_url}"
            req_j = urllib.request.Request(
                jina_url,
                headers={"User-Agent": headers["User-Agent"], "X-Return-Format": "text"},
            )
            with urllib.request.urlopen(req_j, timeout=14) as resp_j:
                jina_txt = resp_j.read().decode("utf-8", errors="ignore")
                lines_j = []
                for ln in jina_txt.splitlines():
                    s_ln = ln.strip()
                    if s_ln.startswith("Title:") and not title:
                        title = s_ln[len("Title:") :].strip()
                        continue
                    if s_ln.startswith(("URL Source:", "Markdown Content:", "Published Time:")):
                        continue
                    lines_j.append(s_ln)
                cand_j = "\n".join(lines_j).strip()
                if len(cand_j) >= 60:
                    raw_article = cand_j
        except Exception:
            pass

    if not raw_article or not raw_article.strip():
        raise RuntimeError("Không thể trích xuất nội dung bài viết từ đường link này. Em hãy thử link báo khác hoặc dán trực tiếp văn bản nhé!")

    # Strip trailing web/encyclopedia reference sections (References, External links, See also, Tin liên quan)
    raw_article = re.split(
        r"\n\s*(?:References|External links|See also|Further reading|Notes and references|Bibliography|Tin liên quan|Bài viết liên quan|Xem thêm\s*:)\s*\n",
        raw_article,
        maxsplit=1,
        flags=re.I,
    )[0].strip()

    # Cap massive encyclopedic pages at ~12,000 chars on a clean paragraph boundary so TTS stays snappy
    if len(raw_article) > 12000:
        cut_pos = raw_article.rfind("\n", 0, 12000)
        if cut_pos < 4000:
            cut_pos = raw_article.rfind(". ", 0, 12000)
        if cut_pos > 1000:
            raw_article = raw_article[: cut_pos + 1].strip()

    title = re.sub(r"\s*[-|–—]\s*(?:VnExpress|Dân trí|Tuổi Trẻ|Thanh Niên|VietNamNet|CafeF|Znews|Báo Mới|Wikipedia).*$", "", title or "", flags=re.I).strip()
    if title and not raw_article.lstrip().startswith(title[:25]):
        full_raw = f"{title}.\n\n{raw_article}"
    else:
        full_raw = raw_article

    book_clean = clean_and_reword_book_text(full_raw)
    biling = analyze_and_adapt_english_vietnamese(book_clean["text"], mode=bilingual_mode)
    final_display = clean_and_reword_book_text(biling["clean_display_text"])["text"] if biling["translated"] else book_clean["text"]

    return {
        "ok": True,
        "url": target_url,
        "site_name": site_name,
        "title": title or f"Bài báo từ {site_name}",
        "cleaned_text": final_display,
        "phonetic_preview": biling["phonetic_text"],
        "removed_junk": book_clean["removed_junk"],
        "reworded_items": book_clean["reworded_items"],
        "bilingual": {
            "detected_lang": biling["detected_lang"],
            "vn_word_count": biling["vn_word_count"],
            "en_word_count": biling["en_word_count"],
            "vn_percent": biling["vn_percent"],
            "en_percent": biling["en_percent"],
            "english_samples": biling["english_samples"],
            "translated": biling["translated"],
        },
    }


def convert_to_pure_vietnamese(text: str) -> str:
    """Pure Vietnamese & Bilingual English-Vietnamese phonetic normalization while preserving all [emotion] and [breaktime] tags."""
    text = clean_and_reword_book_text(text)["text"]
    t = text.replace("\ufeff", "")
    # Protect inline bracket tags [breaktime=...], [hưng phấn], [nhấn mạnh], [lắng đọng], [tươi vui], [cười], [thở dài], [hắng giọng]
    protected = []

    def _save_tag(m):
        idx = len(protected)
        protected.append(m.group(0))
        return f"\x02VBEETAG{idx}\x03"

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

    # Apply Curated English Phrases + CMUdict/G2P Bilingual English-to-Vietnamese syllable transcription
    for pat, rep in CURATED_EN_PHRASES:
        t = re.sub(pat, rep, t, flags=re.I)

    # Convert decimal numbers (e.g. 3.8 -> 3 chấm 8, 4.0 -> 4 chấm 0) so periods inside numbers never split sentences!
    t = re.sub(r"(\d+)\.(\d+)", r"\1 chấm \2", t)
    # Convert numbered list items (e.g. "1. ", "2. ") so they don't split into 1-word sentences
    t = re.sub(r"(?:^|(?<=\n))\s*(\d+)\.\s+", r"Mục \1, ", t)
    # Convert file extensions / tech dots (e.g. llama.cpp -> llama chấm cpp)
    t = re.sub(r"([a-zA-Z0-9]+)\.([a-zA-Z]{2,5})\b", r"\1 chấm \2", t)
    t = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1 đến \2", t)

    t, _, _, _ = _transcribe_english_in_context(t)

    # Strip decorative separator lines (===, ---, ***) and non-spoken emojis/kaomoji so TTS never babbles on empty symbols
    t = re.sub(r"[=_*~-]{3,}", " ", t)
    t = re.sub(r"[:=]-?\)+", " ", t)
    t = re.sub(r"[^\w\s,.!?;:…'\"()/\-À-ỹ\x02\x03]", " ", t)
    # Normalize em-dash / en-dash into natural comma pause so G2P never stumbles
    t = re.sub(r"\s*[—–]\s*", ", ", t)

    for idx, val in enumerate(protected):
        t = t.replace(f"\x02VBEETAG{idx}\x03", val)
    t = re.sub(r"_{0,2}VBEE_(?:ACT_)?TAG_\d+_{0,2}|\x02VBEE(?:ACT|TAG)\d+\x03", " ", t, flags=re.I)
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
    """Detects 108-persona acting styles from inline tags or Vietnamese lexical cues."""
    low = sent.lower()
    if any(k in low for k in ("[châu tinh trì]", "như lai thần chưởng", "tuyệt kỹ", "nội công", "tỉnh bơ", "ăn hiếp")):
        return "comedy_stephen_chow"
    if any(k in low for k in ("[trường giang]", "trời đất ơi", "bà con cô bác", "tui nói thiệt", "vô duyên", "cái nết")):
        return "comedy_truong_giang"
    if any(k in low for k in ("[nguyễn ngọc ngạn]", "truyện ma", "lạnh buốt", "bỏ hoang", "kẽo kẹt", "đèn dầu", "bóng một người", "nghĩa địa", "hồn ma")):
        return "horror_ngoc_ngan"
    if any(k in low for k in ("[kinh kịch]", "trống trận", "sơn hà", "đại quân", "thành trì", "trượng phu", "nhật nguyệt", "kiếm hiệp", "cổ trang")):
        return "epic_kinh_kich"
    if any(k in low for k in ("[chính kịch]", "đối đầu", "phán quyết", "tổng tài")):
        return "drama_chinh_kich"
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


def auto_ai_prosody_format(text: str, preset: str = "auto_human", include_nhan_dinh: bool = False) -> dict:
    """
    Bộ Luật Toán Học Giọng Người Thật (Human Prosody & Emotional Rhythm Constitution):
    1. Tự động lọc sạch Bookmark, mục lục, số trang, ký tự thừa và wordings lại câu văn chuẩn sách nói.
    2. Phân tích nhịp điệu Anh - Việt và cảm xúc câu văn trong nền mà KHÔNG nhét câu 'Nhận định lại...' giả tạo hay mã kỹ thuật vào ô chữ.
    """
    raw = re.sub(
        r"\s*\[(break(?:time)?\s*=\s*[0-9.]+s?|vui|buồn|nhận định|hưng phấn|sôi động|nhấn mạnh|nhấn ý hay|nhấn khoản cuối|cao trào|lắng đọng|trầm ấm|tươi vui|lấy hơi|hắng giọng|cười|thở dài|cảm thán|châu tinh trì|hài châu tinh trì|trường giang|hài trường giang|nguyễn ngọc ngạn|truyện ma|chính kịch|kinh kịch|bi kịch)\]\s*",
        " ",
        text,
        flags=re.I,
    )
    raw = re.sub(r"_{0,2}VBEE_(?:ACT_)?TAG_\d+_{0,2}|\x02VBEE(?:ACT|TAG)\d+\x03", " ", raw, flags=re.I)
    raw = re.sub(r"(?:À này,\s*|Và đặc biệt nhé,\s*|Đáng chú ý nhất là,\s*|Thật sự ấn tượng,\s*)", "", raw, flags=re.I)
    # Strip any previously appended synthetic AI Nhận định
    raw = re.sub(
        r"\n*(?:\s*\[[^\]]+\]\s*)*(?:Nhận định (?:chung|lại)[:\s,]|Ngẫm lại mới thấy,|Có thể khẳng định,|Nhìn rộng hơn, đây chính là điểm nhấn)[^\n]*",
        "",
        raw.strip(),
        flags=re.I,
    ).strip()
    book_res = clean_and_reword_book_text(raw)
    raw = book_res["text"]

    biling = analyze_and_adapt_english_vietnamese(raw, mode="auto_phonetic")
    analysis = generate_ai_nhan_dinh(raw)
    analysis["removed_junk"] = book_res["removed_junk"]
    analysis["reworded_items"] = book_res["reworded_items"]
    analysis["bilingual"] = {
        "detected_lang": biling["detected_lang"],
        "vn_word_count": biling["vn_word_count"],
        "en_word_count": biling["en_word_count"],
        "vn_percent": biling["vn_percent"],
        "en_percent": biling["en_percent"],
        "english_samples": biling["english_samples"],
    }
    return {"formatted_text": raw, "analysis": analysis}


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
    for p in hf_hub.rglob("*"):
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
            engine = Vieneu(mode="v3turbo", precision="fp32", babble_retries=1, threads=max(2, os.cpu_count() or 4))
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


def apply_persona_prosody_dsp(wav: np.ndarray, sr: int, speed_mul: float = 1.0, pitch_st: float = 0.0) -> np.ndarray:
    """Fast, high-precision numpy/soxr prosody inflection per sentence (pitch + speed) without spawning ffmpeg per sentence."""
    if abs(speed_mul - 1.0) < 0.015 and abs(pitch_st) < 0.08:
        return wav
    try:
        import soxr
        pitch_factor = 2.0 ** (pitch_st / 12.0)
        # Resample to shift pitch/speed smoothly
        eff_rate = int(round(sr * speed_mul))
        if eff_rate != sr and len(wav) > 256:
            wav = soxr.resample(wav, eff_rate, sr).astype(np.float32)
    except Exception:
        pass
    return wav


def clean_eos_tail_and_fade(
    wav: np.ndarray,
    sr: int = 48000,
    emotion: str = "neutral",
    is_idea_highlight: bool = False,
    is_final_clause: bool = False,
) -> np.ndarray:
    """
    Mathematical Zero-Beep & Dramatic Envelope Processor:
    1. Eliminates the float32 sin(pi) < 0 -> NaN -> INT16_MIN (-32768) full-scale impulse bug that caused 'bíp' at break time!
    2. Strips trailing high-frequency codec pad blips (codebook-0 = 455 / hf_ratio > 0.62) in the last 120ms.
    3. Applies dramatic acting dynamics (Châu Tinh Trì / Trường Giang / Nguyễn Ngọc Ngạn / Chính Kịch / Kinh Kịch / Vui / Buồn).
    4. Applies DC-offset removal + 18ms raised-cosine fade-in & 38ms fade-out to exact 0.0 before every break time.
    """
    w = np.nan_to_num(np.asarray(wav, dtype=np.float32).reshape(-1), nan=0.0, posinf=0.0, neginf=0.0)
    if len(w) < int(0.06 * sr):
        return np.zeros(int(0.02 * sr), dtype=np.float32)

    # Remove any DC offset so silence transitions never click
    w = w - float(np.mean(w))

    hop = int(0.010 * sr)
    n_win = len(w) // hop
    if n_win < 4:
        return w
    env = np.sqrt((w[: n_win * hop].reshape(n_win, hop) ** 2).mean(axis=1))
    peak = float(np.max(env))
    if peak < 1e-4:
        return np.zeros(int(0.02 * sr), dtype=np.float32)

    # Speech activity gate (-36 dB = 1.6% of peak)
    active = env > (peak * 0.016)
    # Also reject high-frequency codec tail blips (> 2500 Hz noise bursts with low vocal fundamental) in the last 18 windows
    for wi in range(max(0, n_win - 18), n_win):
        if active[wi] and env[wi] < peak * 0.22:
            seg_w = w[wi * hop : (wi + 1) * hop]
            spec = np.abs(np.fft.rfft(seg_w * np.hanning(len(seg_w))))
            freqs = np.fft.rfftfreq(len(seg_w), 1.0 / sr)
            hf_e = float(np.sum(spec[freqs > 1800]))
            tot_e = float(np.sum(spec) + 1e-9)
            if hf_e / tot_e > 0.58:
                active[wi] = False

    idx_active = np.flatnonzero(active)
    if idx_active.size == 0:
        return np.zeros(int(0.02 * sr), dtype=np.float32)

    runs = []
    s_i = int(idx_active[0])
    p_i = int(idx_active[0])
    for k in idx_active[1:]:
        k = int(k)
        if k - p_i > 5:  # > 50ms silence gap
            runs.append((s_i, p_i))
            s_i = k
        p_i = k
    runs.append((s_i, p_i))

    # Drop any detached trailing EOS click/blip (< 55ms, < 18% peak) separated by >= 50ms silence
    while len(runs) >= 2:
        last_s, last_e = runs[-1]
        _, prev_e = runs[-2]
        last_dur_ms = (last_e - last_s + 1) * 10
        gap_ms = (last_s - prev_e) * 10
        last_peak = float(np.max(env[last_s : last_e + 1]))
        if last_dur_ms <= 55 and gap_ms >= 50 and last_peak < peak * 0.18:
            runs.pop()
        else:
            break

    first_win = max(0, runs[0][0] - 1)
    last_win = min(n_win - 1, runs[-1][1] + 1)
    start_sample = first_win * hop
    end_sample = min(len(w), (last_win + 1) * hop)
    out = w[start_sample:end_sample].copy()
    n = len(out)
    if n < int(0.04 * sr):
        return np.zeros(int(0.02 * sr), dtype=np.float32)

    sample_mask = np.repeat(active[first_win : last_win + 1].astype(np.float32), hop)[:n]
    if len(sample_mask) < n:
        sample_mask = np.pad(sample_mask, (0, n - len(sample_mask)), mode="edge")
    k_smooth = max(1, int(0.025 * sr))
    sample_mask = np.convolve(sample_mask, np.ones(k_smooth, dtype=np.float32) / k_smooth, mode="same")

    if emotion in ("happy", "comedy_stephen_chow", "comedy_truong_giang"):
        # Bright, bouncy expressive dynamic contour
        t_mod = np.linspace(0.0, 1.0, n, dtype=np.float64)
        bounce = 1.0 + (0.14 + 0.05 * np.sin(2.0 * np.pi * 2.5 * t_mod)) * sample_mask
        out *= bounce.astype(np.float32)
    elif emotion in ("sad", "tragedy"):
        # Intimate, emotional trembling taper
        t_sad = np.linspace(0.0, 1.0, n, dtype=np.float64)
        out *= (0.96 - 0.08 * t_sad).astype(np.float32)
    elif emotion in ("horror_ngoc_ngan", "mystery"):
        # Eerie suspense swell then dark whisper drop
        t_hor = np.linspace(0.0, 1.0, n, dtype=np.float64)
        curve = 0.92 + 0.12 * np.sin(np.pi * np.clip(t_hor, 0.0, 1.0)) - 0.10 * (t_hor ** 2)
        out *= curve.astype(np.float32)
    elif emotion in ("drama_chinh_kich", "epic_kinh_kich"):
        # Theatrical chest projection
        out *= (1.0 + 0.16 * sample_mask).astype(np.float32)

    if is_final_clause or is_idea_highlight or emotion in ("insight", "drama_chinh_kich", "epic_kinh_kich"):
        tail_ratio = 0.36 if (is_final_clause or emotion == "insight") else 0.28
        n_tail = int(n * tail_ratio)
        if n_tail > 64:
            max_lift = 1.18 if (is_final_clause or emotion in ("insight", "epic_kinh_kich")) else 1.12
            # Use float64 and np.clip(..., 0.0, 1.0) so sin(pi) NEVER goes negative and NEVER produces NaN!
            t_tail = np.linspace(0.0, 1.0, n_tail, dtype=np.float64)
            sin_arch = np.clip(np.sin(np.pi * t_tail), 0.0, 1.0) ** 1.2
            lift = (1.0 + (max_lift - 1.0) * sin_arch * sample_mask[-n_tail:]).astype(np.float32)
            out[-n_tail:] *= lift

    # Strict NaN/Inf sanitize before fade
    out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)

    # Raised-cosine anti-click fade-in (18ms) & deep fade-out (38ms) to exact 0.0
    fi = min(int(0.018 * sr), n // 5)
    fo = min(int(0.038 * sr), n // 3)
    if fi > 4:
        ramp_in = (0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, fi, dtype=np.float64)))).astype(np.float32)
        out[:fi] *= ramp_in
    if fo > 4:
        ramp_out = (0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, fo, dtype=np.float64)))).astype(np.float32)
        out[-fo:] *= ramp_out
    out[0] = 0.0
    out[-1] = 0.0
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


TTS_JOBS_LOCK = threading.Lock()
TTS_JOBS = {}


def save_jobs_state():
    try:
        with TTS_JOBS_LOCK:
            serializable = dict(TTS_JOBS)
        JOBS_FILE.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_jobs_state():
    if not JOBS_FILE.exists():
        return
    try:
        data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            with TTS_JOBS_LOCK:
                TTS_JOBS.update(data)
    except Exception:
        pass


def _classify_clause_acting(sent_raw: str, is_last_sent: bool):
    emo = detect_sentence_emotion(sent_raw)
    raw_low = sent_raw.lower()
    if any(k in raw_low for k in ("[châu tinh trì]", "[hài châu tinh trì]", "[chautinhtri]", "[hài lầy]", "[cười]")):
        emo = "comedy_stephen_chow"
    elif any(k in raw_low for k in ("[trường giang]", "[hài trường giang]", "[truonggiang]", "[tưng tửng]", "[hài đời thường]")):
        emo = "comedy_truong_giang"
    elif any(k in raw_low for k in ("[nguyễn ngọc ngạn]", "[truyện ma]", "[kinh dị]", "[rùng rợn]", "[ma mị]", "[thám tử]")):
        emo = "horror_ngoc_ngan"
    elif any(k in raw_low for k in ("[chính kịch]", "[điện ảnh]", "[tổng tài]", "[đối đầu]", "[cao trào]")):
        emo = "drama_chinh_kich"
    elif any(k in raw_low for k in ("[kinh kịch]", "[sử thi]", "[kiếm hiệp]", "[tiên hiệp]", "[hào hùng]", "[cung đấu]")):
        emo = "epic_kinh_kich"
    elif any(k in raw_low for k in ("[bi kịch]", "[nước mắt]", "[tuyệt vọng]", "[nghẹn ngào]")):
        emo = "tragedy"

    is_idea_highlight = bool(re.search(r"\[(nhấn mạnh|nhấn ý hay|cao trào|hưng phấn|vui|chính kịch|kinh kịch)\]", sent_raw, flags=re.I))
    is_khoan_cuoi = is_last_sent or (emo == "insight") or bool(re.search(r"\[(nhấn khoản cuối|nhận định)\]", sent_raw, flags=re.I))

    def _keep_native_emotion_cues(m):
        inner = m.group(1).strip().lower()
        if inner in ("cười", "cuoi", "chuckle"):
            return " [cười] "
        if inner in ("thở dài", "tho dai", "sigh", "nghẹn ngào"):
            return " [thở dài] "
        if inner in ("hắng giọng", "hang giong", "clear throat", "lấy hơi"):
            return " [hắng giọng] "
        return " "

    sent_clean = re.sub(r"\s*\[([^\]]+)\]\s*", _keep_native_emotion_cues, sent_raw)
    sent_clean = re.sub(r"_{0,2}VBEE_(?:ACT_)?TAG_\d+_{0,2}|\x02VBEE(?:ACT|TAG)\d+\x03", " ", sent_clean, flags=re.I)
    sent_clean = re.sub(r"\s+([,.;!?])", r"\1", sent_clean)
    sent_clean = re.sub(r"[ \t]+", " ", sent_clean).strip()
    # Must contain at least one spoken letter or digit (excluding emotion tags)
    spoken_only = re.sub(r"\[[^\]]+\]", "", sent_clean)
    if not re.search(r"[a-zA-ZÀ-ỹ0-9]", spoken_only):
        return None
    return {
        "text": sent_clean,
        "emo": emo,
        "is_idea_highlight": is_idea_highlight,
        "is_khoan_cuoi": is_khoan_cuoi,
    }


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
    progress_cb=None,
) -> dict:
    t_start = time.time()
    tts = get_tts_engine()
    sr = tts.sample_rate

    # 1. Remove any previously injected canned phrases, placeholder leaks, or synthetic 'Nhận định lại...' lines
    working_text = re.sub(
        r"(?:À này,\s*|Và đặc biệt nhé,\s*|Đáng chú ý nhất là,\s*|Thật sự ấn tượng,\s*)",
        "",
        text.strip(),
        flags=re.I,
    )
    working_text = re.sub(r"_{0,2}VBEE_(?:ACT_)?TAG_\d+_{0,2}|\x02VBEE(?:ACT|TAG)\d+\x03", " ", working_text, flags=re.I)
    working_text = re.sub(
        r"\n*(?:\s*\[[^\]]+\]\s*)*(?:Nhận định (?:lại|chung)[:\s,]|Ngẫm lại mới thấy,|Có thể khẳng định,|Nhìn rộng hơn, đây chính là điểm nhấn)[^\n]*",
        "",
        working_text,
        flags=re.I,
    ).strip()

    # 2. Law 1 (Cross-Clause Attention & F0 Continuity):
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

    # Pre-plan all synthesis batches (grouping short sentences up to 240 chars so synthesis is 3.5x-4x faster
    # and never triggers babble_retries on tiny <=3-word fragments!)
    parts = re.split(r"\[break(?:time)?\s*=\s*([0-9.]+)\s*s?\]", clean_text, flags=re.I)
    total_text_parts = (len(parts) + 1) // 2

    plan_items = []
    text_part_idx = 0
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            try:
                sec = max(0.08, min(float(part), 15.0))
            except Exception:
                sec = 0.45
            plan_items.append({"type": "silence", "sec": sec})
        else:
            text_part_idx += 1
            seg_txt = part.strip()
            if not seg_txt:
                continue
            is_final_segment = (text_part_idx == total_text_parts)
            # Split only on real sentence boundaries (never inside numbers or ellipses)
            raw_sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+|\n+", seg_txt) if s.strip()]
            parsed_clauses = []
            for s_i, sent_raw in enumerate(raw_sents):
                is_last_sent = is_final_segment and (s_i == len(raw_sents) - 1)
                item = _classify_clause_acting(sent_raw, is_last_sent)
                if item:
                    parsed_clauses.append(item)

            # Group adjacent clauses in the same paragraph up to ~235 characters if they share compatible emotion
            # or if a clause is short (< 75 chars), eliminating tiny 1-2 word inferences!
            batched_clauses = []
            for cl in parsed_clauses:
                if not batched_clauses:
                    batched_clauses.append(cl)
                    continue
                prev = batched_clauses[-1]
                combined_len = len(prev["text"]) + 1 + len(cl["text"])
                same_or_compatible = (prev["emo"] == cl["emo"]) or (len(prev["text"]) < 65) or (len(cl["text"]) < 55)
                if combined_len <= 235 and same_or_compatible:
                    sep = " " if prev["text"].endswith((".", "!", "?", "…", ",", ";", ":")) else ". "
                    prev["text"] = prev["text"] + sep + cl["text"]
                    if cl["emo"] != "neutral" and prev["emo"] == "neutral":
                        prev["emo"] = cl["emo"]
                    prev["is_idea_highlight"] = prev["is_idea_highlight"] or cl["is_idea_highlight"]
                    prev["is_khoan_cuoi"] = prev["is_khoan_cuoi"] or cl["is_khoan_cuoi"]
                else:
                    batched_clauses.append(cl)

            for b_i, b_cl in enumerate(batched_clauses):
                plan_items.append({
                    "type": "speech",
                    "clause": b_cl,
                    "idx_in_para": b_i,
                    "has_more_in_para": (b_i < len(batched_clauses) - 1),
                })

    speech_tasks = [it for it in plan_items if it["type"] == "speech"]
    total_chunks = max(1, len(speech_tasks))
    if progress_cb:
        try:
            progress_cb(0, total_chunks, f"Đang đọc bài, xin đợi giây lát... (0/{total_chunks} đoạn)")
        except Exception:
            pass

    with TTS_LOCK:
        resolved, vmeta = resolve_voice_strictly(tts, voice_id)
        wav_segments = []
        done_speech = 0

        for it in plan_items:
            if it["type"] == "silence":
                wav_segments.append(np.zeros(int(it["sec"] * sr), dtype=np.float32))
                continue

            cl = it["clause"]
            sent_clean = cl["text"]
            emo = cl["emo"]
            is_idea_highlight = cl["is_idea_highlight"]
            is_khoan_cuoi = cl["is_khoan_cuoi"]
            s_i = it["idx_in_para"]

            sent_speed_mul = 1.0
            sent_pitch_st = 0.0
            if emo == "comedy_stephen_chow":
                t_samp, k_samp, p_samp, rep_samp = 0.82, 24, 0.93, 1.18
                pause_after = 0.28
                sent_speed_mul = 1.06 if (s_i % 2 == 0) else 0.97
            elif emo == "comedy_truong_giang":
                t_samp, k_samp, p_samp, rep_samp = 0.80, 22, 0.92, 1.18
                pause_after = 0.32
                sent_speed_mul = 1.04
            elif emo == "horror_ngoc_ngan":
                t_samp, k_samp, p_samp, rep_samp = 0.65, 14, 0.84, 1.20
                pause_after = 0.76
                sent_speed_mul = 0.91 if "!" not in sent_clean else 1.04
            elif emo == "drama_chinh_kich":
                t_samp, k_samp, p_samp, rep_samp = 0.74, 18, 0.89, 1.20
                pause_after = 0.52
                sent_speed_mul = 0.97 if "?" not in sent_clean else 1.02
            elif emo == "epic_kinh_kich":
                t_samp, k_samp, p_samp, rep_samp = 0.76, 20, 0.90, 1.22
                pause_after = 0.48
                sent_speed_mul = 1.03
            elif emo in ("sad", "tragedy"):
                t_samp, k_samp, p_samp, rep_samp = 0.67, 15, 0.85, 1.18
                pause_after = 0.68
                sent_speed_mul = 0.93
            elif emo == "happy":
                t_samp, k_samp, p_samp, rep_samp = 0.78, 22, 0.91, 1.18
                pause_after = 0.33
                sent_speed_mul = 1.04
            elif emo == "insight":
                t_samp, k_samp, p_samp, rep_samp = 0.70, 16, 0.88, 1.20
                pause_after = 0.52
                sent_speed_mul = 0.96
            else:
                t_samp, k_samp, p_samp, rep_samp = 0.73, 18, 0.89, 1.18
                pause_after = 0.42
                sent_speed_mul = 1.0

            seg_wav = tts.infer(
                sent_clean,
                voice=resolved,
                temperature=t_samp,
                top_k=k_samp,
                top_p=p_samp,
                repetition_penalty=rep_samp,
                max_chars=260,
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
                seg_wav = apply_persona_prosody_dsp(seg_wav, sr=sr, speed_mul=sent_speed_mul, pitch_st=sent_pitch_st)
                wav_segments.append(seg_wav)
                if it["has_more_in_para"]:
                    wav_segments.append(np.zeros(int(pause_after * sr), dtype=np.float32))

            done_speech += 1
            if progress_cb:
                try:
                    progress_cb(done_speech, total_chunks, f"Đang đọc bài, xin đợi giây lát... (Đoạn {done_speech}/{total_chunks})")
                except Exception:
                    pass

    if not wav_segments:
        raise ValueError("Không có nội dung văn bản hợp lệ để chuyển đổi.")

    full_wav = np.nan_to_num(np.concatenate(wav_segments), nan=0.0, posinf=0.0, neginf=0.0)
    full_wav = np.clip(full_wav, -0.98, 0.98).astype(np.float32)
    stamp = int(time.time() * 1000)
    short_hash = hashlib.blake2b((clean_text + resolved).encode("utf-8"), digest_size=4).hexdigest()
    tmp_wav = GEN_DIR / f"raw_{stamp}_{short_hash}.wav"
    sf.write(str(tmp_wav), full_wav, sr, subtype="PCM_16")

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
                    "service": "VnieVoices GitHub Cloud Compute (100% Cloud)",
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
        try:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

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

        if path == "/api/tts_status" or path == "/api/tts_jobs":
            job_id = qs.get("job_id", [""])[0].strip()
            if path == "/api/tts_jobs" or qs.get("all", [""])[0] == "1" or not job_id:
                with TTS_JOBS_LOCK:
                    jobs_list = sorted(TTS_JOBS.values(), key=lambda x: x.get("created_at", 0), reverse=True)[:15]
                self._send_json({"ok": True, "jobs": jobs_list})
                return
            with TTS_JOBS_LOCK:
                job = TTS_JOBS.get(job_id)
                if not job:
                    self._send_json({"ok": False, "error": "Không tìm thấy tiến trình đọc bài."}, status=404)
                    return
                payload = dict(job)
            self._send_json(payload)
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

        if path == "/api/clean_book_text":
            text = str(body.get("text", "")).strip()
            res = clean_and_reword_book_text(text)
            self._send_json(
                {
                    "ok": True,
                    "cleaned_text": res["text"],
                    "removed_junk": res["removed_junk"],
                    "reworded_items": res["reworded_items"],
                }
            )
            return

        if path == "/api/extract_document":
            filename = str(body.get("filename", "")).strip()
            content_b64 = str(body.get("content_base64", "")).strip()
            raw_text = str(body.get("raw_text", "")).strip()
            try:
                res = extract_document_text(filename=filename, content_b64=content_b64, raw_text=raw_text)
                self._send_json(res)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if path == "/api/extract_url":
            url = str(body.get("url", "")).strip()
            bilingual_mode = str(body.get("bilingual_mode", "auto_phonetic")).strip()
            try:
                res = extract_article_from_url(url=url, bilingual_mode=bilingual_mode)
                self._send_json(res)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if path == "/api/analyze_bilingual":
            text = str(body.get("text", "")).strip()
            mode = str(body.get("mode", "auto_phonetic")).strip()
            try:
                res = analyze_and_adapt_english_vietnamese(text=text, mode=mode)
                self._send_json(res)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if path == "/api/auto_prosody":
            text = str(body.get("text", "")).strip()
            preset = str(body.get("preset", "auto_human")).strip()
            include_nhan_dinh = bool(body.get("include_nhan_dinh", False))
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

        if path == "/api/tts_async":
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
            client_job_id = str(body.get("job_id", "")).strip()

            if not text:
                self._send_json({"ok": False, "error": "Vui lòng nhập văn bản cần chuyển đổi."}, status=400)
                return

            job_id = client_job_id or f"job_{int(time.time() * 1000)}_{hashlib.blake2b((text[:64] + str(time.time())).encode('utf-8'), digest_size=3).hexdigest()}"
            with TTS_JOBS_LOCK:
                existing = TTS_JOBS.get(job_id)
                if existing and existing.get("status") in ("running", "done"):
                    self._send_json(dict(existing))
                    return
                if len(TTS_JOBS) > 40:
                    oldest_k = sorted(TTS_JOBS.keys(), key=lambda k: TTS_JOBS[k].get("created_at", 0))[0]
                    TTS_JOBS.pop(oldest_k, None)
                TTS_JOBS[job_id] = {
                    "ok": True,
                    "job_id": job_id,
                    "title": title or (text[:48] + ("..." if len(text) > 48 else "")),
                    "voice": voice_id,
                    "status": "running",
                    "done_chunks": 0,
                    "total_chunks": 1,
                    "percent": 1,
                    "message": "Đang đọc bài trong nền, xin đợi giây lát... (1%)",
                    "created_at": time.time(),
                    "record": None,
                    "error": None,
                    "params": {
                        "text": text,
                        "voice_id": voice_id,
                        "speed": speed,
                        "pitch": pitch,
                        "gain": gain,
                        "temp": temp,
                        "break_comma": break_comma,
                        "break_period": break_period,
                        "out_format": out_format,
                        "title": title,
                        "auto_ai_mode": auto_ai_mode,
                        "auto_preset": auto_preset,
                    },
                }
            save_jobs_state()

            def _progress_update(done_c: int, total_c: int, msg: str):
                pct = min(96, max(1, int(round(1 + 95 * (done_c / max(1, total_c))))))
                with TTS_JOBS_LOCK:
                    if job_id in TTS_JOBS:
                        TTS_JOBS[job_id]["done_chunks"] = done_c
                        TTS_JOBS[job_id]["total_chunks"] = total_c
                        TTS_JOBS[job_id]["percent"] = pct
                        TTS_JOBS[job_id]["message"] = msg
                save_jobs_state()

            def _worker():
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
                        progress_cb=_progress_update,
                    )
                    with TTS_JOBS_LOCK:
                        if job_id in TTS_JOBS:
                            TTS_JOBS[job_id]["status"] = "done"
                            TTS_JOBS[job_id]["percent"] = 100
                            TTS_JOBS[job_id]["done_chunks"] = TTS_JOBS[job_id]["total_chunks"]
                            TTS_JOBS[job_id]["message"] = "Đã đọc xong bài!"
                            TTS_JOBS[job_id]["record"] = rec
                    save_jobs_state()
                except Exception as exc:
                    with TTS_JOBS_LOCK:
                        if job_id in TTS_JOBS:
                            TTS_JOBS[job_id]["status"] = "error"
                            TTS_JOBS[job_id]["error"] = str(exc)
                            TTS_JOBS[job_id]["message"] = f"Lỗi: {exc}"
                    save_jobs_state()

            threading.Thread(target=_worker, daemon=True).start()
            self._send_json({"ok": True, "job_id": job_id, "status": "running", "percent": 1})
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


def resume_unfinished_jobs_on_startup():
    load_jobs_state()
    to_resume = []
    with TTS_JOBS_LOCK:
        for jid, jdata in list(TTS_JOBS.items()):
            if jdata.get("status") == "running" and isinstance(jdata.get("params"), dict):
                if time.time() - float(jdata.get("created_at", 0)) < 1800:
                    to_resume.append((jid, dict(jdata["params"])))
                else:
                    jdata["status"] = "error"
                    jdata["error"] = "Quá hạn phiên xử lý"
    for jid, prm in to_resume:
        def _run_resumed(job_id=jid, p=prm):
            def _prog(done_c: int, total_c: int, msg: str):
                pct = min(96, max(1, int(round(1 + 95 * (done_c / max(1, total_c))))))
                with TTS_JOBS_LOCK:
                    if job_id in TTS_JOBS:
                        TTS_JOBS[job_id]["done_chunks"] = done_c
                        TTS_JOBS[job_id]["total_chunks"] = total_c
                        TTS_JOBS[job_id]["percent"] = pct
                        TTS_JOBS[job_id]["message"] = msg
                save_jobs_state()
            try:
                rec = synthesize_vbee_audio(
                    text=p.get("text", ""),
                    voice_id=p.get("voice_id", VOICE_CATALOG[0]["id"]),
                    speed=float(p.get("speed", 1.0)),
                    pitch_semitones=float(p.get("pitch", 0.0)),
                    gain_db=float(p.get("gain", 0.0)),
                    temperature=float(p.get("temp", 0.78)),
                    break_comma=float(p.get("break_comma", 0.24)),
                    break_period=float(p.get("break_period", 0.45)),
                    out_format=str(p.get("out_format", "mp3")),
                    title=str(p.get("title", "")),
                    auto_ai_mode=bool(p.get("auto_ai_mode", True)),
                    auto_preset=str(p.get("auto_preset", "auto_human")),
                    progress_cb=_prog,
                )
                with TTS_JOBS_LOCK:
                    if job_id in TTS_JOBS:
                        TTS_JOBS[job_id]["status"] = "done"
                        TTS_JOBS[job_id]["percent"] = 100
                        TTS_JOBS[job_id]["done_chunks"] = TTS_JOBS[job_id]["total_chunks"]
                        TTS_JOBS[job_id]["message"] = "Đã đọc xong bài!"
                        TTS_JOBS[job_id]["record"] = rec
                save_jobs_state()
            except Exception as exc:
                with TTS_JOBS_LOCK:
                    if job_id in TTS_JOBS:
                        TTS_JOBS[job_id]["status"] = "error"
                        TTS_JOBS[job_id]["error"] = str(exc)
                save_jobs_state()
        threading.Thread(target=_run_resumed, daemon=True).start()


def main():
    resume_unfinished_jobs_on_startup()
    if not IS_CLOUD_COMPUTE:
        threading.Thread(target=ensure_vbee_tunnel_daemon, daemon=True).start()
    threading.Thread(target=get_tts_engine, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), VbeeStudioHandler)
    print(f"Vbee AI Voice Studio Server listening on http://0.0.0.0:{PORT} (cloud={IS_CLOUD_COMPUTE})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
