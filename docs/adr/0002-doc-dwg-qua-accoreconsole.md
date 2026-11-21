# ADR-0002: Đọc DWG qua accoreconsole, có cache

- **Ngày:** 2026-11-07 · **Trạng thái:** Chấp nhận

## Bối cảnh
Bản vẽ công trường chủ yếu là DWG. ezdxf chỉ đọc DXF.

## Quyết định
Dùng `accoreconsole.exe` của AutoCAD/Civil 3D để chuyển DWG → DXF (và ghi DWG kết quả). Cache theo nội dung file trong thư mục tạm.

## Lý do & đánh đổi
- Đọc đúng 100% định dạng gốc, không phụ thuộc thư viện bên thứ ba.
- Chỉ chạy trên Windows có AutoCAD; máy khác phải dùng DXF.
- Lần chạy sau cùng file gần như tức thì nhờ cache.
