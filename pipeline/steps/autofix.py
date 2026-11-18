"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict

import yaml

from ..common import ERROR, parse_yolo_line

REMOVE_IMAGE = {"DUP_IMAGE_EXACT", "DUP_IMAGE_NEAR", "LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
DROP_LINE = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
CLIP_BOX = {"BOX_OUT_OF_IMAGE"}


def _rec(image, line, action, before, after):
    return dict(image=image, line=line, action=action, before=before, after=after)


def _clip_line(text):
    """Cắt box về [0,1], giữ lớp. Trả về dòng mới, hoặc None nếu sau khi cắt box không còn diện tích."""
    c, x, y, w, h = parse_yolo_line(text)
    x1, x2 = max(0.0, x - w / 2), min(1.0, x + w / 2)
    y1, y2 = max(0.0, y - h / 2), min(1.0, y + h / 2)
    nx, ny, nw, nh = (round(v, 6) for v in ((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1))
    if nw <= 0 or nh <= 0:                  # so trên giá trị ĐÃ làm tròn: không ghi ra box "0.000000" (sẽ thành BOX_ZERO)
        return None
    return f"{c} {nx:.6f} {ny:.6f} {nw:.6f} {nh:.6f}"


def _remove_images(ds, errs):
    fixes, removed = [], set()
    for i in errs:
        if i.code not in REMOVE_IMAGE or i.image in removed:
            continue
        img, lab = ds.image_path(i.image), ds.label_path(i.image)
        if img is None and not lab.exists():        # đã xoá ở lần chạy trước -> không làm gì (idempotent)
            continue
        before = ", ".join(p.name for p in (img, lab) if p is not None and p.exists())
        if img is not None:
            img.unlink()
        lab.unlink(missing_ok=True)
        removed.add(i.image)
        fixes.append(_rec(i.image, "", "remove_image", before, f"(đã xoá: {i.code})"))
    return fixes, removed


def _rename_classes(ds, errs, cfg):
    if not any(i.code == "BAD_CLASS_NAME" for i in errs):
        return []
    try:                                                    # data.yaml thiếu / hỏng cú pháp -> dựng lại từ đầu
        data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) if ds.yaml_path.exists() else {}
    except yaml.YAMLError:
        data = {}
    data = data if isinstance(data, dict) else {}
    old = data.get("names")
    new = dict(enumerate(cfg["classes"]))
    if old == new or old == cfg["classes"]:                 # đã đúng (dạng dict hoặc list) -> không ghi gì (idempotent)
        return []
    data["names"] = new                                     # giữ các khoá khác (path, train, …), chỉ thay names
    if "nc" in data:
        data["nc"] = len(new)
    ds.yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    return [_rec("data.yaml", "", "rename_classes", str(old), str(new))]


def _fix_lines(ds, errs, removed):
    by_file = defaultdict(lambda: defaultdict(set))       # stem -> số dòng gốc -> {mã lỗi}
    for i in errs:
        if i.code in DROP_LINE | CLIP_BOX and i.line and i.image not in removed:
            by_file[i.image][int(i.line)].add(i.code)

    fixes = []
    for stem in sorted(by_file):
        p = ds.label_path(stem)
        if not p.exists():
            continue
        raw_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        # Duyệt MỘT lần theo số dòng gốc (dòng trống vẫn được đếm), rồi ghi lại file MỘT lần: không lệch số dòng.
        for n, text in enumerate(raw_lines, 1):
            codes = by_file[stem].get(n)
            if not codes or not text.strip():
                out.append(text)
                continue
            if codes & DROP_LINE:                           # xoá dòng thắng: chỉ 1 fix, không clip thêm
                fixes.append(_rec(stem, n, "drop_line", text.strip(), f"(xoá: {', '.join(sorted(codes))})"))
                continue
            try:
                new = _clip_line(text)
            except ValueError:                              # không parse được thì không dám cắt -> để check sau báo
                out.append(text)
                continue
            if new is None:
                fixes.append(_rec(stem, n, "drop_line", text.strip(), "(xoá: box nằm hẳn ngoài ảnh, cắt xong không còn diện tích)"))
                continue
            fixes.append(_rec(stem, n, "clip_box", text.strip(), new))
            out.append(new)
        # newline="\n": luôn ghi LF, kể cả trên Windows (mặc định đổi thành CRLF -> sha1 nhãn trong manifest khác giữa Windows và Linux)
        p.write_text("".join(ln + "\n" for ln in out), encoding="utf-8", newline="\n")
    return fixes


def fix(ds, issues, cfg):
    errs = [i for i in issues if i.severity == ERROR]      # cảnh báo (WARN) là việc của người: không bao giờ động tới

    fixes, removed = _remove_images(ds, errs)               # 1) loại ảnh trước: issue dòng của ảnh đã xoá bỏ qua êm
    fixes += _rename_classes(ds, errs, cfg)                 # 2) data.yaml
    fixes += _fix_lines(ds, errs, removed)                  # 3) sửa dòng nhãn, gom theo file

    # 4) thiếu file nhãn: máy KHÔNG bịa nhãn (kể cả file rỗng = "ảnh nền"), chỉ ghi lại để chuyển người gán
    seen = set()
    for i in errs:
        if i.code == "MISSING_LABEL_FILE" and i.image not in removed and i.image not in seen \
                and ds.image_path(i.image) is not None and not ds.label_path(i.image).exists():
            seen.add(i.image)
            fixes.append(_rec(i.image, "", "needs_label", "(không có file)", "chuyển người gán"))
    return fixes
