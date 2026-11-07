import sys
import os
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from vbee_server import VOICE_CATALOG, synthesize_vbee_audio, PREV_DIR, GEN_DIR
import shutil

PREVIEW_SCRIPTS = {
    # 3 Male TVC Voices
    "Nam TVC Miền Nam — Minh Khôi": "[lắng đọng] Mỗi hành trình đi qua, điều quý giá nhất chính là sự bình yên bên gia đình thân yêu. [breaktime=0.35s] Hãy để chúng tôi đồng hành cùng bạn trên mọi nẻo đường.",
    "Nam TVC Miền Bắc — Hoàng Quân": "[nhấn mạnh] Kiến tạo chuẩn mực sống thượng lưu giữa tâm điểm phồn hoa. [breaktime=0.35s] Nơi hội tụ những giá trị xứng tầm dành riêng cho người dẫn đầu.",
    "Nam TVC Sôi Động — Tuấn Kiệt": "[hưng phấn] Đại tiệc ưu đãi lớn nhất năm đã chính thức bùng nổ! [breaktime=0.25s] Nhanh tay trải nghiệm ngay hôm nay để rinh hàng ngàn quà tặng giá trị!",

    # 20 Northern Female (VTV1 & TVC)
    "Nữ VTV1 & TVC Bắc 01 — Thanh Mai": "[nhấn mạnh] Kính chào quý vị và các bạn đang theo dõi bản tin Thời sự. [breaktime=0.35s] Trong chương trình hôm nay sẽ có những thông tin kinh tế đáng chú ý.",
    "Nữ TVC Bắc 02 — Phương Thảo": "[lắng đọng] Đánh thức mọi giác quan giữa không gian xanh khoáng đạt. [breaktime=0.35s] Nơi mỗi khoảnh khắc trở về đều là một kỳ nghỉ dưỡng đích thực.",
    "Nữ TVC Bắc 03 — Minh Châu": "[nhấn mạnh] Vững vàng tài chính, an tâm tận hưởng cuộc sống thịnh vượng. [breaktime=0.32s] Giải pháp ngân hàng thông minh đồng hành cùng mọi ước mơ của bạn.",
    "Nữ TVC Bắc 04 — Lan Hương": "Chăm sóc sức khỏe chủ động mỗi ngày từ tinh chất thiên nhiên chuẩn hóa. [breaktime=0.32s] Giúp cơ thể luôn dẻo dai và tràn đầy sinh lực.",
    "Nữ TVC Bắc 05 — Thu Hà": "[tươi vui] Đánh thức vẻ đẹp rạng ngời từ sâu bên trong làn da của bạn. [breaktime=0.32s] Cho làn da căng bóng, mịn màng tỏa sáng suốt ngày dài.",
    "Nữ TVC Bắc 06 — Khánh Linh": "[hưng phấn] Săn siêu hội mua sắm giảm giá đến năm mươi phần trăm! [breaktime=0.22s] Chốt đơn liền tay, nhận ngay miễn phí vận chuyển toàn quốc!",
    "Nữ VTV1 Bắc 07 — Bích Ngọc": "[nhấn mạnh] Thị trường chứng khoán và tài chính tuần qua ghi nhận đà tăng trưởng tích cực. [breaktime=0.32s] Dòng vốn đầu tư tiếp tục đổ mạnh vào công nghệ.",
    "Nữ TVC Bắc 08 — Quỳnh Hoa": "Trọn vẹn vị ngon đậm đà cho bữa cơm gia đình thêm ấm cúng. [breaktime=0.35s] Bí quyết giữ lửa yêu thương của hàng triệu căn bếp Việt.",
    "Nữ Truyện Bắc 09 — Hồng Nhung": "[lắng đọng] Đêm đã về khuya, ngoài hiên mưa vẫn rơi từng giọt thật khẽ. [breaktime=0.45s] Có những ký ức tưởng chừng đã ngủ yên lại bất chợt ùa về.",
    "Nữ TVC Bắc 10 — Thùy Dương": "[tươi vui] Khơi dậy niềm đam mê khám phá tri thức cùng phương pháp học tập chuẩn quốc tế. [breaktime=0.32s] Giúp con tự tin vươn ra thế giới.",
    "Nữ TVC Bắc 11 — Bảo Quyên": "Chào mừng quý khách đến với hành trình khám phá những miền đất di sản tuyệt đẹp. [breaktime=0.35s] Kính chúc quý khách một chuyến bay thật êm ái.",
    "Nữ TVC Bắc 12 — Diệu Linh": "[hưng phấn] Đây chính là siêu phẩm đang làm mưa làm gió suốt tuần qua! [breaktime=0.25s] Thiết kế tinh tế, hiệu năng vượt trội trong tầm giá.",
    "Nữ Audiobook Bắc 13 — Mai Phương": "[lắng đọng] Hạnh phúc không nằm ở đích đến, mà hiện diện trong từng bước chân chánh niệm của thực tại. [breaktime=0.4s] Hãy lắng nghe tâm mình.",
    "Nữ TVC Bắc 14 — Hà My": "[hưng phấn] Tự tin khẳng định cá tính riêng cùng bộ sưu tập thời trang thu đông mới nhất! [breaktime=0.25s] Phá vỡ mọi giới hạn phong cách.",
    "Nữ VTV1 Bắc 15 — Tuyết Ngân": "[lắng đọng] Trải qua hàng nghìn năm lịch sử, mảnh đất kinh kỳ vẫn lưu giữ vẹn nguyên hồn cốt văn hóa dân tộc. [breaktime=0.4s] Một vẻ đẹp vượt thời gian.",
    "Nữ Podcast Bắc 16 — Thanh Tâm": "[lắng đọng] Nếu hôm nay bạn cảm thấy đôi chút mỏi mệt, [breaktime=0.3s] hãy cho phép bản thân được nghỉ ngơi và hít một hơi thật sâu nhé.",
    "Nữ TVC Bắc 17 — Ngọc Ánh": "[tươi vui] Nguồn dinh dưỡng mát lành nâng niu từng bước phát triển đầu đời của bé yêu. [breaktime=0.32s] Cùng mẹ trao gửi trọn vẹn yêu thương.",
    "Nữ TVC Bắc 18 — Hoài Thương": "[nhấn mạnh] Chạm tới tương lai cùng công nghệ trí tuệ nhân tạo thế hệ mới. [breaktime=0.3s] Mạnh mẽ, bức phá và dẫn đầu mọi xu hướng.",
    "Nữ TVC Bắc 19 — Kim Oanh": "[lắng đọng] Tết là khoảnh khắc trở về bên mâm cơm ấm áp của mẹ. [breaktime=0.38s] Trao nhau lời chúc bình an, gắn kết tình thân muôn nơi.",
    "Nữ TVC Bắc 20 — Vân Anh": "Cảm ơn quý khách đã liên hệ tổng đài chăm sóc khách hàng. [breaktime=0.3s] Chúng tôi luôn sẵn sàng hỗ trợ quý khách hai mươi tư trên bảy.",

    # 20 Southern Female (HTV Nam Bộ & TVC Sài Gòn)
    "Nữ HTV & TVC Nam 01 — Thùy Trang": "[nhấn mạnh] Kính chào quý khán giả đang theo dõi chương trình Thời sự của Đài Truyền hình Thành phố Hồ Chí Minh. [breaktime=0.35s] Mời quý vị cùng điểm qua các tin tức nổi bật.",
    "Nữ HTV Nam 02 — Ngọc Hân": "[tươi vui] Chào mừng quý vị đến với không gian âm nhạc và đời sống phương Nam. [breaktime=0.32s] Chúc quý vị một buổi trưa thật nhiều niềm vui và năng lượng.",
    "Nữ TVC Nam 03 — Mỹ Tiên": "[tươi vui] Giọt nước mắm truyền thống sánh đặc, thơm lừng hương vị quê nhà Nam Bộ. [breaktime=0.32s] Cho bữa cơm gia đình mình thêm tròn vị yêu thương.",
    "Nữ TVC Nam 04 — Phương Trinh": "[lắng đọng] Tận hưởng liệu trình trẻ hóa chuyên sâu tại không gian làm đẹp chuẩn năm sao. [breaktime=0.35s] Nâng niu nét xuân rạng rỡ của riêng bạn.",
    "Nữ TVC Nam 05 — Khánh Ngân": "[hưng phấn] Lễ hội mua sắm cuối tuần siêu tiết kiệm tại hệ thống siêu thị toàn miền Nam! [breaktime=0.22s] Mua một tặng một, ưu đãi ngập tràn!",
    "Nữ TVC Nam 06 — Bảo Trân": "[nhấn mạnh] Khu đô thị sinh thái ven sông chuẩn mực mới tại trung tâm Sài Gòn. [breaktime=0.35s] Không gian sống xanh an lành cho cả gia đình.",
    "Nữ HTV Nam 07 — Thanh Thảo": "[lắng đọng] Về miền Tây mùa nước nổi, nghe câu hò ngọt lịm giữa mênh mông sông nước Cửu Long. [breaktime=0.38s] Tình người phương Nam mộc mạc mà sâu nặng.",
    "Nữ TVC Nam 08 — Nhã Phương": "[tươi vui] Ly sữa thơm ngon bổ sung canxi và dưỡng chất thiết yếu mỗi sáng. [breaktime=0.28s] Giúp bé cao lớn, thông minh và năng động suốt cả ngày!",
    "Nữ Podcast Nam 09 — Tường Vy": "[lắng đọng] Sài Gòn những chiều mưa bất chợt luôn làm người ta muốn chậm lại một nhịp. [breaktime=0.4s] Cảm ơn bạn đã ghé ngang trạm dừng cảm xúc đêm nay.",
    "Nữ TVC Nam 10 — Minh Thư": "[hưng phấn] Chuyển tiền một chạm, thanh toán siêu tốc chỉ trong tích tắc! [breaktime=0.25s] Mở tài khoản số ngay hôm nay để nhận hoàn tiền cực đỉnh.",
    "Nữ TVC Nam 11 — Hoàng Yến": "Chiết xuất từ thảo dược thiên nhiên lành tính, giúp thanh nhiệt và bảo vệ sức khỏe cả gia đình. [breaktime=0.32s] Sự lựa chọn an tâm của mọi nhà.",
    "Nữ Truyện Nam 12 — Cẩm Ly": "[lắng đọng] Ánh đèn đường hắt qua khung cửa sổ nhỏ, cô khẽ mỉm cười nhớ lại lời hứa năm nào. [breaktime=0.4s] Hóa ra hạnh phúc vẫn luôn ở thật gần.",
    "Nữ TVC Nam 13 — Diễm My": "[tươi vui] Làn da trắng hồng mịn màng không tì vết chỉ sau bảy ngày trải nghiệm! [breaktime=0.28s] Bí quyết tự tin tỏa sáng của phụ nữ hiện đại.",
    "Nữ TVC Nam 14 — Trúc Đào": "[hưng phấn] Đập tan cơn khát mùa hè với vị trà trái cây tươi mát cực sảng khoái! [breaktime=0.22s] Bật nắp ngay, bùng nổ năng lượng tươi trẻ!",
    "Nữ HTV Nam 15 — Kim Ngân": "[nhấn mạnh] Bản tin Kinh tế và Tiêu dùng xin kính chào quý vị. [breaktime=0.32s] Các mặt hàng nông sản chất lượng cao đang được đẩy mạnh xuất khẩu.",
    "Nữ Review Nam 16 — Ái Nhi": "[tươi vui] Hôm nay mình dẫn mọi người đi khám phá một góc ẩm thực Sài Gòn ngon quên lối về luôn nha! [breaktime=0.28s] Hương vị đậm đà khó cưỡng.",
    "Nữ Sách Nói Nam 17 — Huệ Mẫn": "[lắng đọng] Khi tâm bình an, vạn sự bên ngoài đều trở nên nhẹ nhàng như mây trắng. [breaktime=0.42s] Hãy buông bỏ muộn phiền để tìm về sự tĩnh lặng.",
    "Nữ TVC Nam 18 — Quỳnh Như": "[tươi vui] Xuân phương Nam rực rỡ sắc mai vàng, gửi trao món quà sức khỏe vẹn tròn tâm ý. [breaktime=0.35s] Chúc một năm mới an khang thịnh vượng.",
    "Nữ TVC Nam 19 — Thiên Kim": "[nhấn mạnh] Tuyệt tác trang sức kim cương tôn vinh vẻ đẹp quý phái và đẳng cấp vượt thời gian. [breaktime=0.35s] Tỏa sáng khí chất riêng của bạn.",
    "Nữ TVC Nam 20 — Ngọc Bích": "Xin chào quý khách! Rất hân hạnh được đón tiếp và phục vụ quý khách. [breaktime=0.3s] Vui lòng nhấn phím một để gặp chuyên viên tư vấn.",
}

t0 = time.time()
done = 0
for v in VOICE_CATALOG:
    vid = v["id"]
    p_rel = v["preview"]  # e.g. /previews/north_f_01.mp3
    p_name = os.path.basename(p_rel)
    p_dest = PREV_DIR / p_name
    if vid == "Vbee Ngọc Huyền 2.0 (Giọng Mẫu Gốc)" and p_dest.exists():
        continue
    script = PREVIEW_SCRIPTS.get(vid, "Xin chào quý vị và các bạn! [breaktime=0.3s] Đây là giọng đọc truyền cảm chuẩn phòng thu 48 kilohertz.")
    rec = synthesize_vbee_audio(
        text=script,
        voice_id=vid,
        speed=1.0,
        pitch_semitones=0.0,
        gain_db=0.0,
        out_format="mp3",
        title=f"Mẫu giọng: {v['name']}",
        auto_ai_mode=True,
    )
    gen_file = GEN_DIR / os.path.basename(rec["audio_url"])
    if gen_file.exists():
        shutil.copy2(gen_file, p_dest)
        gen_file.unlink(missing_ok=True)
        done += 1
        print(f"[{done:02d}/43] Generated {p_name} ({rec['duration']}) in {rec['elapsed_sec']}s")

print(f"All {done} previews generated in {time.time() - t0:.1f}s!")
