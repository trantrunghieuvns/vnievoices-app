import sys
import subprocess
from pathlib import Path
import soundfile as sf
import imageio_ffmpeg
from vieneu import Vieneu

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
PREV_DIR = Path(r"d:\GS\ANTI\APP\vbee_studio\netlify_site\previews")
PREV_DIR.mkdir(parents=True, exist_ok=True)

tts = Vieneu(mode="v3turbo", precision="fp32")

PREVIEWS = [
    (
        "vbee_ngoc_huyen_goc",
        "Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)",
        "Cúp máy, tôi đứng dựa vào tường, nhìn số dư hơn một triệu đồng trong tài khoản. Nước mắt không kìm được mà rơi xuống."
    ),
    (
        "mc_quyen_linh",
        "MC Quyền Linh (Truyền Cảm Đời Thường)",
        "Bà con mình ơi, đôi khi trong cuộc sống chỉ cần một cái nắm tay thật chặt, một lời động viên đúng lúc cũng đủ giúp nhau vượt qua giông bão."
    ),
    (
        "mc_thanh_bach",
        "MC Thanh Bạch (Sôi Động Sân Khấu)",
        "Xin nồng nhiệt chào đón toàn thể quý vị khán giả đang đến với đêm hội rực rỡ sắc màu và bùng nổ cảm xúc ngay lúc này!"
    ),
    (
        "mc_nguyen_ngoc_ngan",
        "MC Nguyễn Ngọc Ngạn (Kể Chuyện Đêm Khuya)",
        "Quý vị và các bạn thân mến, đêm đã về khuya, ngoài hiên chỉ còn tiếng mưa rơi rả rích trên mái ngói cũ kỹ của căn nhà ngoại ô."
    ),
    (
        "mc_lai_van_sam",
        "MC Lại Văn Sâm (Điềm Đạm Kinh Điển)",
        "Chào mừng quý vị quay trở lại chương trình. Câu hỏi tiếp theo đòi hỏi sự điềm tĩnh và một quyết định thật sự sáng suốt từ bạn."
    ),
    (
        "mc_tran_thanh",
        "MC Trấn Thành (Tự Sự Chạm Cảm Xúc)",
        "Người ta hay hỏi thành công là gì, nhưng thật ra bình yên khi trở về nhà mới là điều quý giá nhất mà đôi khi chúng ta vô tình lãng quên."
    ),
]

for slug, voice_name, sample_text in PREVIEWS:
    print(f"Generating preview for {voice_name}...")
    wav = tts.infer(sample_text, voice=voice_name, temperature=0.78, apply_watermark=False)
    tmp_wav = PREV_DIR / f"{slug}.wav"
    out_mp3 = PREV_DIR / f"{slug}.mp3"
    sf.write(str(tmp_wav), wav, tts.sample_rate)
    subprocess.run([
        FFMPEG, "-y", "-i", str(tmp_wav),
        "-af", "dynaudnorm=f=150:g=15",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(out_mp3)
    ], check=True, capture_output=True)
    tmp_wav.unlink(missing_ok=True)
    print(f" -> Saved {out_mp3.name} ({out_mp3.stat().st_size} bytes)")
