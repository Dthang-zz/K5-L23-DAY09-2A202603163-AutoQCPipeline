"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds

CHECK = "second_opinion"


def _labels_with_lines(ds, stem):
    """Như `ds.valid_boxes` nhưng giữ số dòng gốc: [(số dòng, lớp, (cx, cy, w, h))]. Dòng hỏng / id lạ bị bỏ qua êm."""
    out = []
    for n, text in ds.read_label_lines(stem) or []:
        try:
            c, x, y, w, h = parse_yolo_line(text)
        except ValueError:
            continue
        if 0 <= c < len(ds.classes):
            out.append((n, c, (x, y, w, h)))
    return out


def run(ds, cfg, preds=None):
    so = cfg["second_opinion"]
    conf_thr, min_area, fp_conf = so["conf"], so["min_area_px"], so["fp_conf"]
    iou_missing, iou_match, iou_loose = so["iou_missing"], so["iou_match"], so["iou_loose"]
    names = ds.classes
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    issues = []
    for p in ds.image_files():
        stem = p.stem
        if stem not in preds or not ds.label_path(stem).exists():
            continue                                    # không có ý kiến thứ hai / chưa có nhãn (missing_labels đã báo)
        size = ds.image_size(stem)
        if size is None:
            continue                                    # ảnh hỏng: check images đã báo
        W, H = size
        labels = _labels_with_lines(ds, stem)
        rows = [(int(r[0]), float(r[1]), tuple(map(float, r[2:6]))) for r in preds[stem]]

        def add(code, msg, line=None, **extra):
            issues.append(Issue(CHECK, WARN, code, stem, msg, line, {k: round(v, 4) if isinstance(v, float) else v for k, v in extra.items()}))

        # (A) Mỗi dự đoán TIN CẬY (conf >= conf, đủ lớn) sinh tối đa MỘT cảnh báo, theo thứ tự trong preds.
        for pc, pconf, pb in rows:
            if pconf < conf_thr or pb[2] * W * pb[3] * H < min_area:
                continue
            cands = [(iou_xywh(pb, lb), lc, ln) for ln, lc, lb in labels]
            cands = [c for c in cands if c[0] >= iou_missing]
            if not cands:
                add("POSSIBLE_MISSING", f"model thấy {names[pc]} (conf {pconf:.2f}) mà nhãn không có box", conf=pconf, pred_class=pc)
                continue
            same = [c for c in cands if c[1] == pc]
            if same:
                best = max(same)
                if best[0] < iou_loose:
                    add("POSSIBLE_LOOSE_BOX", f"box {names[pc]} dòng {best[2]} lệch/lỏng so với model (IoU {best[0]:.2f} < {iou_loose})",
                        conf=pconf, iou=best[0], label_line=best[2])
                continue                                # nhãn đúng lớp đã phủ vật này -> không cờ
            best = max(cands)                           # chỉ còn nhãn khác lớp
            if best[0] >= iou_match:
                add("POSSIBLE_WRONG_CLASS", f"nhãn {names[best[1]]} (dòng {best[2]}) nhưng model nói {names[pc]} (conf {pconf:.2f}, IoU {best[0]:.2f})",
                    conf=pconf, iou=best[0], label_line=best[2], label_class=best[1], pred_class=pc)
            # IoU khác lớp trong [iou_missing, iou_match): mơ hồ -> không cờ

        # (B) Box nhãn không khớp vật nào model thấy (mọi dự đoán conf >= fp_conf, KHÔNG lọc diện tích, không xét lớp).
        loose_preds = [pb for _, pconf, pb in rows if pconf >= fp_conf]
        for ln, lc, lb in labels:
            best = max((iou_xywh(pb, lb) for pb in loose_preds), default=0.0)
            if best < iou_missing:
                add("POSSIBLE_FALSE_POS", f"box {names[lc]} không khớp vật nào model thấy (IoU tốt nhất {best:.2f} < {iou_missing})",
                    line=ln, iou=best, label_class=lc)
    return issues
