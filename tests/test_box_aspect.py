"""Test cho check thêm `box_aspect` (tỉ lệ khung hình box). Ảnh giả 640×480, cfg test có min_box_px = 12."""
from pipeline.checks import box_aspect

SIZE = (640, 480)


def found(issues):
    return [(i.code, i.image, i.line) for i in issues]


def tall_people(n, start=0.30):
    """n box person đứng (rộng 64 px, cao 144..~190 px): rộng/cao ≈ 0.34–0.44."""
    return [f"1 0.5 0.5 0.1 {start + 0.005 * k:.3f}" for k in range(n)]


def test_normal_boxes_are_silent(make_ds, cfg):
    ds = make_ds(images={"a": 1}, labels={"a": ["0 0.5 0.5 0.3 0.2", "1 0.2 0.5 0.1 0.3", "2 0.7 0.5 0.25 0.3"]}, size=SIZE)
    assert box_aspect.run(ds, cfg) == []


def test_sliver_box_is_extreme_with_line_number(make_ds, cfg):
    ds = make_ds(images={"a": 1}, labels={"a": ["0 0.5 0.5 0.3 0.2", "0 0.5 0.5 0.9 0.04"]}, size=SIZE)   # 576 × 19.2 px: 30 lần
    iss = box_aspect.run(ds, cfg)
    assert found(iss) == [("BOX_ASPECT_EXTREME", "a", 2)]
    assert iss[0].severity == "warn" and abs(iss[0].extra["ratio"] - 30) < 0.1


def test_ratio_is_measured_in_pixels_not_normalized_units(make_ds, cfg):
    # chuẩn hoá: 0.05/0.5 = 0.1 (10 lần, sẽ bị báo nếu tính sai); pixel: 32/240 ≈ 0.133 (7.5 lần < 8) -> im lặng
    ds = make_ds(images={"a": 1}, labels={"a": ["1 0.5 0.5 0.05 0.5"]}, size=SIZE)
    assert box_aspect.run(ds, cfg) == []


def test_wide_person_is_odd_for_its_class(make_ds, cfg):
    labels = tall_people(20) + ["1 0.5 0.5 0.4 0.15", "0 0.5 0.5 0.4 0.15"]      # person bè như ô tô; car cùng hình thì bình thường
    ds = make_ds(images={"a": 1}, labels={"a": labels}, size=SIZE)
    iss = box_aspect.run(ds, cfg)
    assert found(iss) == [("BOX_ASPECT_CLASS", "a", 21)]
    assert iss[0].extra["z"] > 3.5 and iss[0].extra["class_median"] < 0.5


def test_class_with_few_boxes_has_no_class_statistics(make_ds, cfg):
    ds = make_ds(images={"a": 1}, labels={"a": tall_people(5) + ["1 0.5 0.5 0.4 0.15"]}, size=SIZE)
    assert box_aspect.run(ds, cfg) == []


def test_statistics_are_pooled_over_the_whole_dataset(make_ds, cfg):
    imgs = {s: k for k, s in enumerate("abcd", 1)}
    labels = {"a": tall_people(7), "b": tall_people(7, 0.34), "c": tall_people(6, 0.38), "d": ["1 0.5 0.5 0.4 0.15"]}
    ds = make_ds(images=imgs, labels=labels, size=SIZE)
    assert found(box_aspect.run(ds, cfg)) == [("BOX_ASPECT_CLASS", "d", 1)]


def test_one_issue_per_box_and_extreme_wins(make_ds, cfg):
    ds = make_ds(images={"a": 1}, labels={"a": tall_people(20) + ["1 0.5 0.5 0.9 0.04"]}, size=SIZE)
    assert found(box_aspect.run(ds, cfg)) == [("BOX_ASPECT_EXTREME", "a", 21)]


def test_bad_lines_are_skipped_and_line_numbers_kept(make_ds, cfg):
    labels = ["garbage", "", "93 0.5 0.5 0.9 0.04", "1 0.5 0.5 0 0.3", "0 0.5 0.5 0.9 0.04"]
    ds = make_ds(images={"a": 1}, labels={"a": labels}, size=SIZE)
    assert found(box_aspect.run(ds, cfg)) == [("BOX_ASPECT_EXTREME", "a", 5)]


def test_tiny_boxes_are_ignored(make_ds, cfg):
    ds = make_ds(images={"a": 1}, labels={"a": ["0 0.5 0.5 0.5 0.01"]}, size=SIZE)   # cao 4.8 px < 12: việc của BOX_TINY
    assert box_aspect.run(ds, cfg) == []


def test_thresholds_come_from_config_with_defaults_for_missing_keys(make_ds, cfg):
    ds = make_ds(images={"a": 1}, labels={"a": tall_people(20) + ["1 0.5 0.5 0.9 0.04"]}, size=SIZE)
    cfg["box_aspect"] = {"max_ratio": 40}                      # sợi chỉ 30 lần không còn EXTREME ...
    assert found(box_aspect.run(ds, cfg)) == [("BOX_ASPECT_CLASS", "a", 21)]   # ... nhưng vẫn lạ với lớp (z_thresh mặc định)
    cfg["box_aspect"] = {"max_ratio": 40, "z_thresh": 1000}
    assert box_aspect.run(ds, cfg) == []


def test_identical_boxes_do_not_divide_by_zero(make_ds, cfg):
    same = ["1 0.5 0.5 0.1 0.3"] * 20
    ds = make_ds(images={"a": 1}, labels={"a": same + ["1 0.5 0.5 0.12 0.3", "1 0.5 0.5 0.2 0.3"]}, size=SIZE)
    # MAD = 0 -> dùng min_spread 0.1: lệch 20% (z≈1.8) im lặng, lệch gấp đôi (z≈6.9) bị báo
    assert found(box_aspect.run(ds, cfg)) == [("BOX_ASPECT_CLASS", "a", 22)]


def test_unreadable_image_or_missing_label_is_skipped(make_ds, cfg):
    ds = make_ds(images={"a": b"not an image", "b": 2}, labels={"a": ["0 0.5 0.5 0.9 0.04"]}, size=SIZE)
    assert box_aspect.run(ds, cfg) == []


def test_cli_writes_report(make_ds, cfg, tmp_path, monkeypatch):
    ds = make_ds(images={"a": 1}, labels={"a": ["0 0.5 0.5 0.9 0.04"]}, size=SIZE)
    monkeypatch.setattr(box_aspect, "load_config", lambda p: cfg)
    box_aspect.main(["--data", str(ds.root), "--out", str(tmp_path / "rep")])
    assert "BOX_ASPECT_EXTREME" in (tmp_path / "rep.txt").read_text(encoding="utf-8")
    assert (tmp_path / "rep.csv").exists()
