"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line

CHECK = "label_format"


def _overflow(x, y, w, h):
    """Mức tràn lớn nhất (tỉ lệ ảnh) của 4 mép box ra ngoài [0,1]; 0 nếu box nằm trong ảnh."""
    return max(0.0, -(x - w / 2), (x + w / 2) - 1, -(y - h / 2), (y + h / 2) - 1)


def run(ds, cfg):
    lf = cfg["label_format"]
    tol, min_px, max_frac, dup_iou = lf["overflow_tol"], lf["min_box_px"], lf["max_box_frac"], lf["dup_box_iou"]
    n_cls = len(ds.classes)
    issues = []

    for lp in ds.label_files():
        stem = lp.stem
        size = ds.image_size(stem)          # (W, H) px; None nếu ảnh không có/hỏng -> không kiểm BOX_TINY
        prev = []                           # (số dòng, lớp, box) mọi dòng hợp lệ TRƯỚC ĐÓ, để so DUP_BOX

        for n, text in ds.read_label_lines(stem) or []:   # n = số dòng gốc (dòng trống vẫn được đếm)
            # 1) cú pháp: dòng hỏng thì báo rồi bỏ qua, không kiểm hình học
            try:
                c, x, y, w, h = parse_yolo_line(text)
            except ValueError as e:
                issues.append(Issue(CHECK, ERROR, "BAD_FORMAT", stem, f"không đúng 5 cột số ({e}): {text.strip()!r}", n))
                continue
            if not 0 <= c < n_cls:
                issues.append(Issue(CHECK, ERROR, "BAD_CLASS_ID", stem, f"id lớp {c} ngoài 0..{n_cls - 1}", n, {"class_id": c}))
                continue
            if w <= 0 or h <= 0:
                issues.append(Issue(CHECK, ERROR, "BOX_ZERO", stem, f"box rộng/cao bằng 0 (w={w}, h={h})", n))
                continue

            # 2) hình học
            over = _overflow(x, y, w, h)
            if over > tol:
                issues.append(Issue(CHECK, ERROR, "BOX_OUT_OF_IMAGE", stem, f"box tràn ra ngoài ảnh {over:.4f} (> {tol})", n,
                                    {"overflow": round(over, 6)}))

            # 3) box lặp: cùng lớp với một dòng hợp lệ TRƯỚC ĐÓ và IoU > dup_box_iou -> báo ở dòng SAU (dòng đầu tiên trùng)
            box = (x, y, w, h)
            dup = next(((m, iou) for m, pc, pb in prev if pc == c and (iou := iou_xywh(pb, box)) > dup_iou), None)
            if dup:
                issues.append(Issue(CHECK, ERROR, "DUP_BOX", stem, f"trùng box dòng {dup[0]} (cùng lớp, IoU {dup[1]:.3f} > {dup_iou})", n,
                                    {"of_line": dup[0], "iou": round(dup[1], 4)}))
            prev.append((n, c, box))

            # 4) cảnh báo kích thước (đo trên box như ghi trong file)
            if size:
                short = min(w * size[0], h * size[1])
                if short < min_px:
                    issues.append(Issue(CHECK, WARN, "BOX_TINY", stem, f"cạnh ngắn {short:.1f}px < {min_px}px", n, {"short_px": round(short, 2)}))
            if w * h > max_frac:
                issues.append(Issue(CHECK, WARN, "BOX_HUGE", stem, f"box phủ {w * h:.1%} ảnh (> {max_frac:.0%})", n, {"area_frac": round(w * h, 4)}))
    return issues
