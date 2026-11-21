# CODEMAP.md — Bản đồ code SanNenPro

> Dành cho AI tìm nhanh chỗ cần sửa. Cập nhật khi thêm/xoá file hoặc hàm lớn.
> Cách chạy, tham số, layer, JSON: xem AGENTS.md.

## File
| File | Vai trò |
|---|---|
| `sannen.py` | Lõi: đọc bản vẽ → dựng TIN → chia lưới → tính → kiểm tra → xuất Excel/PDF/DXF/DWG. CLI `main()`, API `run()` |
| `sannen3d.py` | Xuất 3D: DWG solid (qua AutoCAD), HTML xem 3D, IFC4, LandXML. Gọi từ `run()` khi `--3d` |
| `sannen3d_view.html` | Template trang xem 3D (JS thuần, không phụ thuộc ngoài), `sannen3d.write_html` đổ dữ liệu vào |
| `sannen_gui.py` | Giao diện Tkinter + kéo thả; là entry của bản `.exe` |
| `sannen.lsp` | Lệnh AutoCAD `SANNEN`, `SANNENKQ`, `SANNEN3D` |
| `test_sannen.py` | 55 bài kiểm tra so với đáp số giải tích. Chạy: `python test_sannen.py` → `TONG: n / n` |
| `config_mau.json` | Mẫu `--config`: cao độ từng khu, mặt nghiêng, mái riêng |
| `CAI_DAT.bat`, `CHAY_SAN_NEN.bat`, `build.bat` | Cài venv, chạy kéo-thả, đóng gói PyInstaller |
| `mau/` | Bản vẽ mẫu + kết quả mẫu. KHÔNG sửa khi test |
| `ban-chay/` | Bản .zip phát hành cho người dùng |
| `docs/` | GitHub Pages: `index.html` giới thiệu tool. `docs/timtim-sapa/` là trang riêng, không liên quan tool |

## Luồng chính trong `sannen.py`
```
main() → run(inputs, cfg, out)
  read_sources → load_raw (cache) → scan_entities → pick_layers → make_source
  build_zones  → fix_boundaries (cắt chồng lấn, lấp khe)
  TIN (mặt đất) + Design / pick_design (mặt thiết kế)
  compute      → make_grid → cell_calc / split_cell   (lưới ô, kiểu HML)
               → Overlay (tam giác TIN cắt theo ô; có TIN thiết kế thì cắt chồng cả hai — tính chính xác)
               → calc_taluy, calc_pits, calc_piles
               → balance / balance_full                (cao độ cân bằng)
  quality      → warnings / errors / fixed
  write_excel, write_pdf, write_dxf (+ dxf_to_dwg)
  sannen3d.export (khi --3d)
  summary      → SanNen_KetQua.json
```

## Muốn sửa gì → sửa ở đâu
| Muốn... | Chỗ sửa |
|---|---|
| Đọc thêm loại entity / thuộc tính cao độ | `scan_entities`, `ELEV_TAGS`, `text_xy`, `line_pts` |
| Tự nhận layer theo tên | `pick_layers`, `DEFAULTS` |
| Mặt đất, ngoại suy ngoài vùng điểm | `class TIN`, `hull_extrap` |
| Mặt thiết kế phẳng / nghiêng / TIN | `class Design`, `pick_design` |
| Cách tính lưới ô | `make_grid`, `split_cell`, `cell_calc` |
| Cách tính TIN chính xác | `class Overlay` |
| Taluy | `taluy_ctx`, `taluy_eval`, `calc_taluy` |
| Hố móng, hố giật cấp | `calc_pits` |
| Cọc khoan nhồi | `calc_piles` |
| Ngưỡng cảnh báo / lỗi | `quality`, `check_points` |
| Mẫu Excel | `write_excel` (công thức: `recalc_excel`) |
| Mẫu PDF | `write_pdf` |
| Mặt bằng DWG, layer xuất | `write_dxf`, `LAYERS` |
| Đường dẫn AutoCAD | `ACAD_GLOB`, `find_accore` |
| Khối 3D, màu theo bề dày | `sannen3d.model_3d`, `band_rgb`, `write_dxf3d` |
| Kiểm tra thể tích 3D (MASSPROP) | `sannen3d.acad_script`, `read_mpr` |
