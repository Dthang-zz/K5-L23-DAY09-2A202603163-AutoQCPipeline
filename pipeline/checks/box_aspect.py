"""CHECK THÊM (thưởng) — Tỉ lệ khung hình của box: box "sợi chỉ" và box có hình dạng lạ so với lớp của nó.

Test:  pytest tests/test_box_aspect.py -q
Chạy:  python -m pipeline.checks.box_aspect --data work/run/ds --out submission/reports/extra_box_aspect

Ý tưởng: lỗi nhầm lớp hợp lệ (car↔person, car↔truck) không bắt được bằng cú pháp và model lớn cũng có lúc bỏ qua.
Nhưng mỗi lớp có hình dạng điển hình: người đứng thì cao (rộng/cao < 1), ô tô thì bè (rộng/cao > 1).
Một box "person" bè ngang như ô tô là đáng mở ra xem. Tất cả chỉ là CẢNH BÁO (người xem), không sửa gì.

| code               | severity | khi nào                                                                                       |
|--------------------|----------|-----------------------------------------------------------------------------------------------|
| BOX_ASPECT_EXTREME | WARN     | max(r, 1/r) > `max_ratio`, với r = rộng_px / cao_px (box dạng "sợi chỉ", vd. box bị cắt sát mép) |
| BOX_ASPECT_CLASS   | WARN     | lớp có ≥ `min_class_boxes` box; |log r − trung vị lớp| / độ phân tán > `z_thresh`                |

- Tỉ lệ đo theo PIXEL (cần `ds.image_size`): box 0.3×0.4 trên ảnh 640×480 là 192×192 px, tỉ lệ 1.
- Độ phân tán = max(1.4826 × MAD của log r trong lớp, `min_spread`) — MAD là thống kê "bền", một vài box sai
  không kéo lệch chuẩn; `min_spread` tránh chia cho 0 khi mọi box giống hệt nhau.
- Thống kê tính trên TOÀN dataset (mọi ảnh), chỉ dùng box đủ lớn (cạnh ngắn ≥ `cfg["label_format"]["min_box_px"]`):
  box nhỏ vài pixel có tỉ lệ rất nhiễu (đã có BOX_TINY lo).
- Mỗi box tối đa MỘT issue (EXTREME ưu tiên). Dòng hỏng / id lạ / box rỗng bị bỏ qua êm (label_format đã báo).
- Ngưỡng: `cfg["box_aspect"]` nếu có, thiếu khoá nào thì lấy `DEFAULTS` (configs/pipeline.yaml là quy tắc dự án
  cố định nên không thêm mục mới vào đó).
"""
from __future__ import annotations

import argparse
import math
import statistics
from collections import defaultdict

from ..common import ROOT, WARN, Dataset, Issue, load_config, parse_yolo_line

CHECK = "box_aspect"
DEFAULTS = {"max_ratio": 8.0, "min_class_boxes": 20, "z_thresh": 3.5, "min_spread": 0.1}


def params(cfg):
    return {**DEFAULTS, **(cfg.get("box_aspect") or {})}


def _boxes(ds, min_px):
    """[(stem, số dòng, lớp, log r)] các box hợp lệ, đủ lớn, của ảnh mở được; theo thứ tự ảnh rồi số dòng."""
    out = []
    for p in ds.image_files():
        size = ds.image_size(p.stem)
        if size is None:
            continue
        W, H = size
        for n, text in ds.read_label_lines(p.stem) or []:
            try:
                c, _, _, w, h = parse_yolo_line(text)
            except ValueError:
                continue
            if not 0 <= c < len(ds.classes) or w <= 0 or h <= 0:
                continue
            wp, hp = w * W, h * H
            if min(wp, hp) < min_px:
                continue
            out.append((p.stem, n, c, math.log(wp / hp)))
    return out


def run(ds, cfg):
    k = params(cfg)
    boxes = _boxes(ds, cfg["label_format"]["min_box_px"])
    log_max = math.log(k["max_ratio"])

    # thống kê theo lớp: trung vị và độ phân tán (MAD) của log r
    by_cls = defaultdict(list)
    for _, _, c, lr in boxes:
        by_cls[c].append(lr)
    stat = {}
    for c, v in by_cls.items():
        if len(v) >= k["min_class_boxes"]:
            med = statistics.median(v)
            mad = statistics.median(abs(x - med) for x in v)
            stat[c] = (med, max(1.4826 * mad, k["min_spread"]))

    issues = []
    for stem, n, c, lr in boxes:
        r = math.exp(lr)
        name = ds.classes[c]
        if abs(lr) > log_max:
            issues.append(Issue(CHECK, WARN, "BOX_ASPECT_EXTREME", stem,
                                f"box {name} dạng sợi chỉ: rộng/cao = {r:.2f} (vượt {k['max_ratio']:g} lần)", n,
                                {"ratio": round(r, 3)}))
            continue
        if c in stat:
            med, spread = stat[c]
            z = abs(lr - med) / spread
            if z > k["z_thresh"]:
                issues.append(Issue(CHECK, WARN, "BOX_ASPECT_CLASS", stem,
                                    f"box {name} có rộng/cao = {r:.2f}, lạ so với lớp {name} (điển hình {math.exp(med):.2f}, z = {z:.1f}): nhầm lớp hay box lỏng?",
                                    n, {"ratio": round(r, 3), "class_median": round(math.exp(med), 3), "z": round(z, 2)}))
    return issues


def main(argv=None):
    from ..steps.report import write_report

    ap = argparse.ArgumentParser(description="Check tỉ lệ khung hình box (chạy riêng, không ảnh hưởng gate).")
    ap.add_argument("--data", default="work/run/ds", help="thư mục dataset YOLO (images/, labels/)")
    ap.add_argument("--out", default="submission/reports/extra_box_aspect", help="tiền tố file báo cáo (.csv, .txt)")
    ap.add_argument("--config", default="configs/pipeline.yaml")
    a = ap.parse_args(argv)
    cfg = load_config(ROOT / a.config)
    ds = Dataset(ROOT / a.data, cfg["classes"])
    issues = run(ds, cfg)
    n = len(ds.image_files())
    write_report(issues, ROOT / a.out, f"Check thêm — tỉ lệ khung hình box ({a.data})", n)
    print(f"quét {n} ảnh: {len(issues)} cảnh báo, {len({i.image for i in issues})} ảnh -> {a.out}.txt/.csv")


if __name__ == "__main__":
    main()
