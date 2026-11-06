# Hướng dẫn cho AI chạy SanNenPro

Tài liệu này dành cho trợ lý AI (Claude, ChatGPT, Copilot...) hoặc script tự động chạy `sannen.py`. Người dùng thường xem `README.md`.

## Việc AI được làm và không được làm

- Không sửa file bản vẽ đầu vào. Chương trình chỉ đọc, kết quả ghi vào thư mục `--out`.
- Không tự đoán thông số thiết kế. Thiếu cao độ thiết kế, hệ số K, hệ số mái, chiều dày bóc, cao độ đáy hố hoặc chiều dài cọc thì hỏi người dùng.
- Không báo số khi `errors` trong JSON khác rỗng mà chưa nêu rõ các lỗi đó.
- Báo cáo cả số lưới ô và số TIN, nói rõ đang dùng cách tính nào.

## Cài đặt

Cần Python 3.10 trở lên.

```bash
git clone https://github.com/huyhoang31897-stack/SanNenPro
cd SanNenPro
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux, macOS: .venv/bin/python
python test_sannen.py                                     # dòng cuối phải là TONG: 31 / 31
```

Đọc DWG cần `accoreconsole.exe` của AutoCAD trên Windows. Trên Linux, macOS hoặc máy không có AutoCAD, yêu cầu người dùng lưu bản vẽ sang DXF.

## Quy trình

1. Xem layer trong bản vẽ:

   ```bash
   python sannen.py "ban ve.dxf" --list-layers
   ```

   Kết quả JSON có `layers` (số điểm, polyline, circle, block, khoảng cao độ của từng layer) và `auto` (layer chương trình tự nhận). Đối chiếu với người dùng nếu `auto` có `pts` hoặc `bdy` là `null`, hoặc khoảng cao độ không hợp lý.

2. Chạy tính, chỉ định layer khi cần:

   ```bash
   python sannen.py "ban ve.dxf" --td 2.5 --step 5 --k 1.15 \
     --layer pts=CAO_DO --layer bdy=RANH \
     --taluy-dao 1 --taluy-dap 1.5 --boc 0.3 \
     --mai-ho 0.5 --dai-coc 20 --json --out KetQua
   ```

   Với `--json`, stdout chỉ có JSON, nhật ký ra stderr.

3. Đọc mã thoát và JSON, xem bảng dưới.

4. Trả cho người dùng: tổng khối lượng, đất thừa hoặc thiếu, các `warnings`, `errors`, `fixed`, và đường dẫn file trong `files`.

Nhiều file: truyền nhiều đường dẫn, điểm đo được gộp chung, mỗi polyline ranh giới là một khu.

## Mã thoát

| Mã | Nghĩa | Xử lý |
|---|---|---|
| 0 | Tính xong | Dùng kết quả, vẫn phải đọc `warnings` |
| 2 | Sai đầu vào: thiếu file, thiếu điểm cao độ, thiếu ranh giới, thiếu cao độ thiết kế | Đọc stderr, sửa tham số hoặc hỏi người dùng |
| 3 | Tính xong nhưng có LỖI trong kiểm tra số liệu | Báo `errors` trước khi dùng số |

## Tham số

| Tham số | Đơn vị | Ý nghĩa |
|---|---|---|
| `--td` | m | Cao độ thiết kế phẳng cho mọi khu |
| `--step`, `--rot` | m, độ | Bước lưới, góc lưới. Bỏ `--rot` thì lưới theo cạnh dài ranh giới |
| `--k` | | m³ đất đào cần cho 1 m³ đắp đã đầm |
| `--taluy-dao`, `--taluy-dap` | m | Hệ số mái 1:m. Bỏ trống là không tính |
| `--boc` | m | Chiều dày bóc phong hoá, trừ vào mặt đất trước khi tính |
| `--mai-ho` | m | Hệ số mái hố móng 1:m, 0 là thành đứng |
| `--day-ho` | m | Cao độ đáy hố khi trong polyline không có TEXT cao độ |
| `--dai-coc`, `--d-coc` | m | Dài cọc khoan nhồi; đường kính khi tim cọc là block |
| `--layer LOAI=TEN` | | LOAI: `pts`, `tk`, `bdy`, `brk`, `noslope`, `pit`, `pile`, `grid` |
| `--use-grid` | | Dùng lưới và nhãn HML trong bản vẽ để đối chiếu |
| `--no-fix-ranh` | | Không tự cắt chồng lấn, lấp khe hở |
| `--config` | | File JSON, xem `config_mau.json`: cao độ từng khu, mặt nghiêng, mái riêng từng khu |
| `--json`, `--no-dwg`, `--out` | | Xuất JSON ra stdout, bỏ DWG, thư mục kết quả |

## Layer

| Loại | Mặc định | Dữ liệu |
|---|---|---|
| `pts` | `TL-CDTN` | TEXT, MTEXT, POINT có Z, block có thuộc tính cao độ |
| `tk` | `TL-CDTK` | Cao độ thiết kế dạng điểm |
| `bdy` | `TL-Ranhgioi` | Polyline kín, mỗi khu một polyline |
| `brk` | `TL-Breakline` | Line, polyline có Z; Z = 0 thì lấy cao độ mặt đất |
| `noslope` | `TL-KhongTaluy` | Line dọc cạnh không làm mái: tường chắn, ranh đất |
| `pit` | `TL-HoMong` | Polyline kín, TEXT cao độ đáy đặt bên trong |
| `pile` | `TL-Coc` | CIRCLE đúng đường kính, hoặc block kèm `--d-coc` |

Không có layer mặc định thì chương trình dò theo tên và nội dung. Luôn xem `layers` trong JSON để biết layer đã dùng.

## JSON kết quả

Có ở stdout khi dùng `--json`, luôn lưu tại `<out>/SanNen_KetQua.json`.

| Khóa | Nội dung |
|---|---|
| `totals` | `fill_grid_m3`, `cut_grid_m3`, `fill_tin_m3`, `cut_tin_m3`, `strip_m3`, `slope_fill_m3`, `slope_cut_m3`, `pit_m3`, `pile_m3`, `surplus_tin_m3`, `area_m2` |
| `zones` | Khối lượng từng khu |
| `pits`, `piles` | Từng hố móng, từng nhóm cọc |
| `balance` | `level_inside`: cao độ cân bằng trong ranh; `level_all_items`: gồm taluy, hố móng, cọc |
| `warnings`, `errors`, `fixed` | Kết quả kiểm tra số liệu, các chỉnh sửa ranh giới đã tự làm |
| `layers`, `params`, `files` | Layer đã dùng, thông số, file đã xuất |

`surplus_tin_m3` = đào + taluy đào + hố móng + cọc − K × (đắp + taluy đắp). Đất bóc phong hoá không tính vào phần dùng lại.

## Dùng trong Python

```python
import sannen
cfg = dict(sannen.DEFAULTS, td=2.5, k=1.15, strip=0.3, taluy_cut=1.0, taluy_fill=1.5)
r = sannen.run(["ban ve.dxf"], cfg, out="KetQua", no_dwg=True)
print(r["summary"]["totals"])
```
