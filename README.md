# SanNenPro 2.0

Tool tính khối lượng san nền bằng Python, đọc từ DWG/DXF và xuất Excel, DWG, PDF.

**Tải bản chạy ngay (không cần Python):** vào mục [Releases](https://github.com/huyhoang31897-stack/SanNenPro/releases/latest), tải `SanNenPro_v2.0.zip`, giải nén, chạy `SanNenPro.exe`, xem `HUONG_DAN.txt`.

## Chạy từ mã nguồn
Chạy `CAI_DAT.bat` một lần (cần Python 3.10 trở lên), rồi:

```
python sannen_gui.py
python sannen.py "ban ve.dwg" --td -0.6 --step 5 --k 1.15
python sannen.py a.dwg b.dwg --td 2.5 --taluy-dao 1 --taluy-dap 1.5 --out KetQua
python sannen.py "ban ve hml.dwg" --use-grid
python test_sannen.py
```

| Tham số | Ý nghĩa |
|---|---|
| `--td` | Cao độ thiết kế phẳng cho mọi khu |
| `--step` / `--rot` | Bước lưới (m), góc lưới; bỏ trống góc thì theo cạnh dài ranh giới |
| `--k` | m³ đất đào cần cho 1 m³ đắp đã đầm |
| `--taluy-dao` / `--taluy-dap` | Hệ số mái m (1:m); bỏ trống là không tính |
| `--use-grid` | Dùng lưới và nhãn HML trong bản vẽ để đối chiếu |
| `--no-fix-ranh` | Không tự sửa chồng lấn, khe hở |
| `--config` | Cao độ từng khu, mặt nghiêng, tên layer (xem `config_mau.json`) |

## Cách tính
- **Lưới ô:** cao độ đỉnh nội suy trên TIN, làm tròn 2 số lẻ; ô cắt theo đường h = 0; `V = S × trung bình |h|`.
- **TIN:** cắt tam giác theo ô, tích phân chính xác. Đường gãy được ép thành cạnh tam giác bằng cách chèn điểm giữa.
- **Taluy:** lưới điểm 0,5 m ngoài ranh, mái 1:m tính từ mép gần nhất đến khi gặp mặt đất, chỉ giữ phần liền với ranh giới.
- **Ranh giới:** chồng lấn thuộc khu đứng trước, khe hở nhập vào khu kề.
- **Tốc độ:** đọc song song, kết quả đọc lưu trong thư mục tạm `sannenpro_cache`.

## Khác HML
Với cùng cao độ nút, script khớp HML ở mọi ô trừ các ô có đỉnh h = 0 đúng bằng 0: HML chia trung bình khác ở một số ô này, script dùng công thức thường. Xem cột Nguyên nhân ở sheet `Đối chiếu HML`.

## Giới hạn
- Taluy áp dụng cho toàn bộ chu vi ngoài.
- Chưa tính bóc phong hoá, cọc két, hầm, hố móng.
- Cao độ cân bằng chưa gồm taluy.
- Thiết kế dạng TIN điểm lấy cao độ tại đỉnh tam giác nên là gần đúng.
