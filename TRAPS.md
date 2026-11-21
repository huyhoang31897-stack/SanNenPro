# TRAPS.md — Bẫy đã dính, đừng lặp lại

> Mất >15 phút vì một lỗi → ghi vào đây. AI đọc trước khi sửa phần tính toán.
> Mẫu: Triệu chứng / Nguyên nhân / Cách đúng / Ngày.

### [T-001] Bỏ sót phần khu nằm ngoài vùng điểm đo
- **Triệu chứng:** Diện tích tính ra nhỏ hơn diện tích ranh, khối lượng thiếu.
- **Nguyên nhân:** TIN chỉ phủ trong bao lồi các điểm cao độ; phần ranh ngoài bao lồi bị bỏ.
- **Cách đúng:** Kéo dài cao độ liên tục từ điểm ngoài cùng (`hull_extrap`), vẫn tính đủ diện tích, và báo % diện tích ngoại suy (<0,5% OK, <5% cảnh báo, ≥5% lỗi).
- **Ngày:** 2026-11-07

### [T-002] Hố móng chồng nhau bị tính trùng
- **Triệu chứng:** Tổng đào hố lớn hơn thực tế khi có hố giật cấp hoặc hố giao nhau.
- **Nguyên nhân:** Mỗi polyline hố tính riêng, phần giao bị cộng hai lần.
- **Cách đúng:** Gộp các hố, tính một lần theo đáy thấp nhất; phần chung gán cho hố sâu hơn; ghi quan hệ vào `pits[].note`. Có test trong `test_sannen.py`.
- **Ngày:** 2026-11-07

### [T-003] Mặt thiết kế không phẳng: khối lượng TIN phụ thuộc bước lưới
- **Triệu chứng:** Đổi `--step` thì khối lượng TIN thay đổi.
- **Nguyên nhân:** Tính trên lưới khi cả mặt đất lẫn mặt thiết kế đều gãy khúc.
- **Cách đúng:** Cắt chồng TIN đất × TIN thiết kế (`Overlay`) để mỗi mảnh phẳng ở cả hai mặt; cân bằng bằng độ dịch cả mặt (`balance.mode = offset`), không phải một cao độ phẳng.
- **Ngày:** 2026-11-07

### [T-004] Tam giác phẳng ở đỉnh đồi / đáy trũng khi chỉ có đồng mức
- **Triệu chứng:** Đỉnh đồi bị "cắt bằng", khối lượng lệch.
- **Nguyên nhân:** Cả 3 đỉnh tam giác nằm trên cùng một đường đồng mức.
- **Cách đúng:** Kiểm tra và báo diện tích tam giác phẳng; đề nghị người dùng bổ sung điểm cao độ ở đó. Không tự bịa điểm.
- **Ngày:** 2026-11-07

### [T-005] Đọc DWG trên máy không có AutoCAD
- **Triệu chứng:** Lỗi không tìm thấy `accoreconsole.exe` (Linux, macOS, máy không cài AutoCAD).
- **Nguyên nhân:** DWG chỉ đọc được qua accoreconsole chuyển sang DXF.
- **Cách đúng:** Nhờ người dùng lưu sang DXF. Không thử thư viện đọc DWG khác.
- **Ngày:** 2026-11-21

### [T-006] Cache đọc bản vẽ trả dữ liệu cũ sau khi sửa `scan_entities`
- **Triệu chứng:** Sửa cách đọc entity nhưng kết quả không đổi.
- **Nguyên nhân:** `load_raw` cache theo đường dẫn + kích thước + mtime + `SCAN_VER`.
- **Cách đúng:** Mỗi lần đổi logic `scan_entities` thì tăng `SCAN_VER`.
- **Ngày:** 2026-11-21
