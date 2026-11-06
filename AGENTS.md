# Hướng dẫn cho AI chạy SanNenPro

Tài liệu này dành cho trợ lý AI (Claude, ChatGPT, Copilot...) hoặc script tự động chạy `sannen.py`. Người dùng thường xem `README.md`.

Người dùng chính của tool là AI: người dùng mô tả việc cần làm bằng lời, AI chạy lệnh và báo kết quả. Giao diện chỉ dùng khi cần thao tác tay.

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
python test_sannen.py                                     # dòng cuối phải là TONG: n / n (hai số bằng nhau)
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
     --mai-ho 0.5 --dai-coc 20 --3d --json --out KetQua
   ```

   Với `--json`, stdout chỉ có JSON, nhật ký ra stderr. Mặc định luôn thêm `--3d`, trừ khi người dùng không cần mô hình 3D.

3. Đọc mã thoát và JSON, xem bảng dưới.

4. Trả cho người dùng: tổng khối lượng, đất thừa hoặc thiếu, các `warnings`, `errors`, `fixed`, và đường dẫn file trong `files`. Có `--3d` thì báo thêm kết quả `check_3d` (thể tích khối solid so với bảng tính) và nhắc người dùng: xem nhanh bằng `SanNen_3D.html`, xem trong AutoCAD bằng `SanNen_3D.dwg` hoặc lệnh `SANNEN3D`.

Nhiều file: truyền nhiều đường dẫn, điểm đo được gộp chung, mỗi polyline ranh giới là một khu.

## Mã thoát

| Mã | Nghĩa | Xử lý |
|---|---|---|
| 0 | Tính xong | Dùng kết quả, vẫn phải đọc `warnings` |
| 2 | Sai đầu vào: thiếu file, thiếu điểm cao độ, thiếu ranh giới, thiếu cao độ thiết kế | Đọc stderr, sửa tham số hoặc hỏi người dùng |
| 3 | Tính xong nhưng có LỖI trong kiểm tra số liệu | Báo `errors` trước khi dùng số |

## Mặt thiết kế

- Phẳng: `--td`, hoặc cao độ từng khu trong `--config`.
- Mặt nghiêng: khai báo `plane` trong `--config` (z0, x0, y0, ix, iy).
- Chỗ cao chỗ thấp: đặt điểm cao độ thiết kế trên layer `tk` và bỏ `--td`. Chương trình dựng TIN thiết kế, cắt chồng TIN đất với TIN thiết kế để mỗi mảnh tính đều phẳng ở cả hai mặt, nên khối lượng TIN tính đúng tuyệt đối, không phụ thuộc bước lưới. Khi báo kết quả, nói rõ cân bằng là độ dịch cả mặt (`balance.mode` = `offset`).

## Tham số

| Tham số | Đơn vị | Ý nghĩa |
|---|---|---|
| `--td` | m | Cao độ thiết kế phẳng cho mọi khu. Bỏ trống khi bản vẽ có layer điểm cao độ thiết kế (mặt chỗ cao chỗ thấp) |
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
| `--3d` | | Xuất `SanNen_3D.dwg`, `SanNen_3D.html`, `SanNen_3D.ifc`, `SanNen_TIN.xml` |
| `--json`, `--no-dwg`, `--out` | | Xuất JSON ra stdout, bỏ DWG, thư mục kết quả |

## Layer

| Loại | Mặc định | Dữ liệu |
|---|---|---|
| `pts` | `TL-CDTN` | TEXT, MTEXT, POINT có Z, block có thuộc tính cao độ |
| `tk` | `TL-CDTK` | Cao độ thiết kế dạng điểm. Các điểm khác cao độ thì dựng TIN thiết kế; chỗ nằm ngoài vùng điểm lấy cao độ kéo dài từ biên vùng điểm và có cảnh báo |
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
| `balance` | `mode`: `level` khi mọi khu thiết kế phẳng, `offset` khi có mặt thiết kế không phẳng. Với `level`: `level_inside`, `level_all_items` là cao độ san phẳng để cân bằng. Với `offset`: hai giá trị đó là độ nâng (+) hoặc hạ (-) cả mặt thiết kế để cân bằng, giữ nguyên hình dạng mặt. `level_inside` chỉ tính trong ranh, `level_all_items` gồm taluy, hố móng, cọc |
| `warnings`, `errors`, `fixed` | Kết quả kiểm tra số liệu, các chỉnh sửa ranh giới đã tự làm |
| `layers`, `params`, `files` | Layer đã dùng, thông số, file đã xuất |
| `check_3d` | Có khi chạy `--3d`. `mesh`: thể tích khối lưới so với bảng tính. `solid.layers`: thể tích MASSPROP của từng layer solid trong `SanNen_3D.dwg` so với bảng tính. `solid.mesh_left`: số khối chưa đổi được sang solid, khác 0 thì báo người dùng. `solid` là null khi máy không có AutoCAD |

`surplus_tin_m3` = đào + taluy đào + hố móng + cọc − K × (đắp + taluy đắp). Đất bóc phong hoá không tính vào phần dùng lại.

## File 3D

| File | Mở bằng | Nội dung |
|---|---|---|
| `SanNen_3D.dwg` | AutoCAD, hoặc lệnh `SANNEN3D` trong bản vẽ gốc | Khối solid thật: nền sau san (xám), khối đắp (xanh), khối đào (đỏ), bóc phong hoá (nâu, layer tắt sẵn), hố móng, cọc, mái taluy, mặt đất xung quanh. Mỗi khu một khối, chọn khối gõ `MASSPROP` ra đúng thể tích trong bảng tính. Bên phải có hình tách khối kèm chữ ghi khối lượng. Đúng toạ độ bản vẽ, đơn vị m. Máy không có AutoCAD thì ra `SanNen_3D.dxf` dạng mesh |
| `SanNen_3D.html` | Trình duyệt bất kỳ, cả điện thoại | Mặt đất, mặt thiết kế tô màu đào đắp, taluy, hố móng, cọc. Thanh kéo cao độ san tính lại đào đắp ngay, nút Cân bằng, mặt cắt, bấm ô xem khối lượng |
| `SanNen_3D.ifc` | Navisworks: Open hoặc Append. Revit: Insert > Link IFC | IFC4. Khối đắp, khối đào từng khu có thuộc tính khối lượng, mặt đất, mặt thiết kế, mái taluy, hố móng, cọc. Toạ độ thật của bản vẽ, đơn vị m |
| `SanNen_TIN.xml` | Civil 3D: Insert > LandXML | Mặt TIN hiện trạng và thiết kế |

Thanh kéo trong file HTML tính lại phần trong ranh; taluy chỉ đúng ở cao độ thiết kế gốc.

Có AutoCAD thì bước 3D mất thêm khoảng 30 giây với khu 1,6 ha, khu lớn hơn lâu hơn. Không cần 3D thì bỏ `--3d` để chạy nhanh.

## Dùng trong Python

```python
import sannen
cfg = dict(sannen.DEFAULTS, td=2.5, k=1.15, strip=0.3, taluy_cut=1.0, taluy_fill=1.5)
cfg["export_3d"] = True
r = sannen.run(["ban ve.dxf"], cfg, out="KetQua", no_dwg=True)
print(r["summary"]["totals"])
```
