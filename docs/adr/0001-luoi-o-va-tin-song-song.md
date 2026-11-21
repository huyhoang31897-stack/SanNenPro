# ADR-0001: Chạy song song lưới ô và TIN

- **Ngày:** 2026-11-07 · **Trạng thái:** Chấp nhận

## Bối cảnh
Tư vấn và CĐT quen bảng tính lưới ô kiểu HML. Lưới ô là gần đúng, sai số phụ thuộc bước lưới.

## Quyết định
Tính cả hai: lưới ô (giống HML, để đối chiếu và trình duyệt) và TIN chính xác (cắt chồng TIN đất × mặt thiết kế, tích phân từng tam giác).

## Lý do & đánh đổi
- Có số quen thuộc để trình và có số chính xác để kiểm.
- Báo cáo phải ghi rõ đang dùng số nào.
- Đổi lại: code dài hơn, phải giữ hai cách tính khớp nhau trong test.
