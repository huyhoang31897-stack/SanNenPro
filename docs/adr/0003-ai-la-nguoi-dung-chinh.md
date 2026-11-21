# ADR-0003: AI là người dùng chính — CLI + JSON + mã thoát

- **Ngày:** 2026-11-07 · **Trạng thái:** Chấp nhận

## Bối cảnh
Người dùng mô tả việc bằng lời, AI chạy tool. Giao diện chỉ dùng khi cần thao tác tay.

## Quyết định
- `--json`: stdout chỉ có JSON, nhật ký ra stderr.
- Mã thoát 0 / 2 (sai đầu vào) / 3 (có lỗi kiểm tra số liệu).
- `--list-layers` để AI dò layer trước khi tính.
- Hướng dẫn cho AI nằm trong `AGENTS.md`.

## Lý do & đánh đổi
- AI đọc kết quả chắc chắn, không phải phân tích văn bản.
- Phải giữ ổn định tên khoá JSON; đổi khoá là đổi giao diện, cần ghi PROGRESS và ADR.
