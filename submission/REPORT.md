# Day 09 Lab — Tạ Đức Thắng: 2A202603163 - Tạ Đức Thắng

Cấu hình: `phash_dist = 12`, `second_opinion.conf = 0.6` (các mục khác giữ nguyên). Số liệu lấy từ `submission/reports/` (lần `make run` cuối, mã thoát 10) và `submission/calibration/`.

## 1. Kết luận trước

**HOLD** (mã thoát 10). Quét **224** ảnh → loại **22** ở cửa vào → **202** ảnh qua QC và được xuất vào `export/clean_v1` dưới dạng **bản NHÁP** (`manifest.json`: `decision: Hold`), **không phải bản phát hành**.
Lý do: sau sửa tự động + người duyệt, `07_error_list_v3` còn **0 lỗi bắt buộc**, nhưng **38/202 ảnh (18,8%)** còn cảnh báo chưa có người xem, ≥ ngưỡng 10%. Gốc rễ: hàng đợi cần duyệt **125 ảnh** > ngân sách **80 ảnh**.

## 2. Lỗi và phân việc

Từ `01_intake` (mẫu số 224 ảnh) và `02_error_list_v1` (mẫu số 202 ảnh sau cửa vào).

| Mã lỗi                                                 |                            Số ảnh/dòng | Ai sửa                                | Vì sao                                                                 |
| ------------------------------------------------------ | -------------------------------------: | ------------------------------------- | ---------------------------------------------------------------------- |
| `CORRUPT_IMAGE` / `BAD_SIZE`                           |                   2 / 3 ảnh (trên 224) | máy: loại ở cửa vào                   | không mở được / cạnh ngắn < 250 px: không dùng được để train           |
| `DUP_IMAGE_EXACT` / `DUP_IMAGE_NEAR`                   |                              8 / 4 ảnh | máy: loại                             | trùng làm lệch phân bố; giữ ảnh đứng trước                             |
| `LEAK_TEST`                                            |                                  5 ảnh | máy: loại                             | trùng ảnh test/val → metric đẹp giả                                    |
| `MISSING_LABEL_FILE`                                   |                                  6 ảnh | **người** gán (máy ghi `needs_label`) | máy không được bịa nhãn; file rỗng nghĩa là "ảnh nền", khác "chưa gán" |
| `BAD_FORMAT` / `BAD_CLASS_ID` / `BOX_ZERO` / `DUP_BOX` |                     3 / 6 / 4 / 7 dòng | máy: `drop_line` (20 dòng)            | lỗi cú pháp, không có cách sửa an toàn ngoài xoá dòng                  |
| `BOX_OUT_OF_IMAGE`                                     |                                 8 dòng | máy: `clip_box`                       | cắt về [0,1], giữ lớp (vd. `img_0043` dòng 1: w 0.267 → 0.237)         |
| `BAD_CLASS_NAME`                                       | 2 issue (`data.yaml`: `Person`, `Bus`) | máy: `rename_classes`                 | sửa đúng `cfg.classes`, 1 thay đổi                                     |
| `POSSIBLE_MISSING`                                     |                      53 issue / 52 ảnh | người                                 | lỗi ngữ nghĩa: máy chỉ nghi ngờ                                        |
| `POSSIBLE_WRONG_CLASS`                                 |                            18 / 18 ảnh | người                                 | car↔truck↔bus, car↔person: cần mắt người                               |
| `POSSIBLE_LOOSE_BOX`                                   |                            28 / 24 ảnh | người                                 | box lệch, không biết box nào đúng                                      |
| `POSSIBLE_FALSE_POS`                                   |                            29 / 27 ảnh | người                                 | model không thấy vật: có thể box thừa, có thể model sót                |
| `EMPTY_LABEL`                                          |                        12 ảnh (v2: 15) | người                                 | ảnh nền hay thiếu nhãn?                                                |
| `BOX_TINY` / `BOX_HUGE`                                |                   7 dòng/5 ảnh · 3 ảnh | người                                 | quy tắc dự án, không phải lỗi chắc chắn                                |
| `CLASS_RARE`                                           |      4 (cấp dataset: lớp −1, 4, 7, 93) | hết sau khi máy xoá ID sai            | triệu chứng của `BAD_CLASS_ID`                                         |

Tổng: 36 lỗi bắt buộc + 154 cảnh báo (v1) → 35 thay đổi tự động (`03_fixes.csv`: 20 `drop_line`, 8 `clip_box`, 6 `needs_label`, 1 `rename_classes`) → v2 còn đúng 6 lỗi bắt buộc (6 ảnh thiếu nhãn).

**Hàng đợi** (`05_review_queue.csv`, 125 ảnh): ưu tiên = Σ trọng số × (1 + conf) của cảnh báo + điểm cho dòng đã bị máy sửa + 10 cho ảnh chưa có nhãn. `img_0020` đứng đầu (11,52) vì có cùng lúc `WRONG_CLASS` (trọng số 3), `MISSING` (2) và một dòng bị xoá (`FIXED_DROP_LINE`); ngay sau là 6 ảnh `NEEDS_LABEL` (10,0) vì không có người thì không thể Release. Ngân sách cắt ở ảnh thứ 80 (ưu tiên 3,343; ảnh 81: 3,333).
Người đã xem **74/103 ảnh có cảnh báo ngữ nghĩa**: `WRONG_CLASS` 18/18, `MISSING` 50/52, `FALSE_POS` 12/23, `LOOSE_BOX` 8/24. Trên 74 ảnh có nhãn được duyệt, người đã đổi lớp 22 box (21 ảnh), thêm 123 box, xoá 60 box (so nhãn sau sửa tự động với nhãn sau duyệt). 45 ảnh không được xem chủ yếu mang cảnh báo trọng số thấp (`LOOSE_BOX` 16, `FALSE_POS` 11).

## 3. Calibration (2 ngưỡng)

| Tham số                 | Khởi đầu | Đã chọn | Precision / Recall (trước → sau)                                                                                                                              | Lý do (đánh đổi)                                                                                                                                                                                                                                                                                                                                                     |
| ----------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `duplicates.phash_dist` | 2        | **12**  | `DUP_IMAGE_NEAR` 1,00/0,50 → 1,00/0,67 (`EXACT` giữ 1,00/1,00)                                                                                                | Lỗi này **xoá ảnh** nên ưu tiên precision. 4–14 cho kết quả như nhau trên calib; trên raw 10–14 loại cùng 22 ảnh. Cặp trùng thật xa nhất trên raw ở khoảng cách 10 (`img_0186`~`img_0061`), cặp ảnh khác nhau gần nhất ở 16 → chọn 12 ở giữa. So với 2, bắt thêm `img_0186`, `img_0223` (trùng gần) và `img_0101` (rò rỉ `test_039`), cả 3 đã mở xem: đúng là trùng. |
| `second_opinion.conf`   | 0.25     | **0.6** | `MISSING` 0,50/1,00 → 0,57/1,00 · `WRONG_CLASS` 0,56/0,83 → 0,62/0,83 · `LOOSE_BOX` 0,29/0,40 → 0,20/0,20 · `FALSE_POS` 0,31/1,00 (không đổi, dùng `fp_conf`) | Cảnh báo cho người nên ưu tiên recall: 0.6 là mức cao nhất mà recall `MISSING`/`WRONG_CLASS` chưa giảm (0.7: `MISSING` R 0,88; 0.8: 0,75). Trên raw, `MISSING` 152 → 53 cờ, hàng đợi 143 → 125 ảnh. Cái giá: `LOOSE_BOX` R 0,40 → 0,20 (2 → 1 trên 5 lỗi chèn); chấp nhận vì box lỏng ít hại hơn thiếu vật/nhầm lớp, nhưng ghi là điểm yếu (§4b).                    |

**Chỗ calibration đánh lừa** (có bằng chứng):

1. **`phash_dist = 16` có F1 cao nhất trên calib (0,91) nhưng hại trên raw.** Ở 16, raw bị loại thêm 9 ảnh (22 → 31); mở xem cả 9 cặp thì chỉ **1** là trùng thật (`img_0084` là bản cắt của `img_0074`), **8** là ảnh khác hẳn: `img_0011` (tennis) ~ `img_0008` (trượt tuyết), `img_0177` (lướt sóng) ~ `img_0113` (người ngồi bàn), `img_0013`/`img_0017`/`img_0021`/`img_0033`/`img_0038`/`img_0115` bị báo `LEAK_TEST` với ảnh test không liên quan. Ở 20 thì 134/224 ảnh bị báo trùng/rò rỉ (105 `LEAK_TEST`). Lý do: calib **không có ca `LEAK_TEST`** nên FP rò rỉ không bị tính, và ảnh khác nhau trong calib cách nhau ≥ 20 còn trên raw có cặp chỉ cách 16.
2. **`conf = 0.8` cho Release (16/202 = 7,9%) — Release giả.** Hàng đợi nhỏ đi vì checker bỏ sót (calib: `MISSING` R 0,75, `LOOSE_BOX` R 0,20), không phải vì dữ liệu sạch hơn. Tôi không chọn ngưỡng theo kết luận gate.
3. Calib chỉ có 5–8 lỗi chèn mỗi mã: một lỗi = 12–20 điểm phần trăm recall, nên chênh giữa 0.5 và 0.6 nằm trong nhiễu.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được

**(a) Gate chặn đúng.** `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb --work work/run_nb` → kết luận **REWORK**, **mã thoát 20**: "còn 6 lỗi bắt buộc (MISSING_LABEL_FILE: 6)" (`img_0031`, `img_0053`, `img_0126`, `img_0135`, `img_0170`, `img_0219`). Log ghi "KHÔNG xuất: còn lỗi bắt buộc (Rework)" và thư mục `work/exp_nb` **không được tạo**. Autofix chỉ ghi `needs_label` (`03b_fixes_after_review.csv`), không tạo file nhãn. Lần chạy chính (ngân sách 80) 6 ảnh này nằm ngay đầu hàng đợi, được người gán → 0 lỗi bắt buộc → Hold chứ không Rework.

**(b) Điểm mù đã thấy:**

1. **Ảnh trùng biến đổi mạnh.** `img_0084` (bản cắt của `img_0074`, phash 16) lọt qua: cả hai đều có trong `manifest.json`. Không ngưỡng nào bắt được mà không loại nhầm 8 ảnh khác (§3). Calib có 2 ca tương tự không bắt được (`calib_037`: 16, `calib_038`: 18).
2. **Nhầm car↔truck mà model lớn không cờ.** Trong 21 ảnh người đổi lớp, 3 ảnh **không** có `POSSIBLE_WRONG_CLASS`: `img_0078` (car→truck), `img_0024` (truck→car), `img_0220` (car→truck). Chúng được sửa chỉ vì vào hàng đợi do cảnh báo khác; ảnh tương tự ngoài hàng đợi sẽ lọt. truck (41 box) và bus (32 box) cũng là lớp ít nhất (`class_stats.csv`: car 101, person 574).
3. **Box lỏng nhẹ.** `iou_loose = 0.5` (cố định): box lệch mà IoU ≥ 0,5 không bị cờ. Người đã chỉnh 111 box ở mức IoU 0,5–0,9 trên ảnh duyệt, trong khi chỉ 8 ảnh duyệt có cờ `LOOSE_BOX`; recall calib 0,20.
4. **Sửa tự động tạo "ảnh nền" giả.** Xoá dòng lỗi duy nhất làm file rỗng: `img_0050` (`BOX_ZERO`), `img_0104`, `img_0194` (`BAD_CLASS_ID`) → `EMPTY_LABEL` tăng 12 → 15. Ba ảnh này được người duyệt, nhưng nếu ngân sách nhỏ hơn chúng sẽ được xuất như ảnh nền.
5. **Báo động giả trên raw nhiều hơn calib cho thấy.** 25/80 ảnh đã duyệt vẫn còn cảnh báo sau khi đã thay bằng nhãn người (11 `MISSING`, 10 `FALSE_POS`, 4 `LOOSE_BOX`, 3 `WRONG_CLASS`): model bất đồng với chính nhãn người.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)

Colab T4, `notebooks/day09_train_compare.ipynb` → `scripts/train_compare.py`: **yolo26n**, **20 epoch**, batch 16, imgsz 640, **seed 0 và 1**, cùng val (`gold_val`, 40 ảnh) và cùng test (100 ảnh, nhãn người). `raw` = 224 ảnh nhãn gốc; `clean` = 202 ảnh của export **Hold** (bản nháp, `manifest_sha1` 882dadf… khớp export hiện tại). Bảng từ `submission/results/comparison.md`:

| biến thể | #ảnh train | số seed | mAP50 (TB ± độ lệch) | mAP50-95      | precision     | recall        |
| -------- | ---------- | ------- | -------------------- | ------------- | ------------- | ------------- |
| raw      | 224        | 2       | 0.726 ± 0.000        | 0.512 ± 0.004 | 0.764 ± 0.061 | 0.649 ± 0.028 |
| clean    | 202        | 2       | 0.701 ± 0.025        | 0.487 ± 0.008 | 0.759 ± 0.003 | 0.625 ± 0.019 |

AP50 theo lớp (TB 2 seed, từ `*_seed*.json`): car 0,738 → 0,738 · person 0,822 → 0,823 · bus 0,695 → 0,703 · **truck 0,648 → 0,538 (−0,11)**.

**So với nhiễu:** chênh mAP50 (clean − raw) = **−0,025**, đúng bằng độ lệch giữa 2 seed của `clean` (0,025; hai seed 0,718 và 0,683). Với 2 seed, khác biệt **nằm trong nhiễu**: **chưa kết luận được** clean tốt hơn hay kém hơn raw. mAP50-95 giảm 0,024, lớn hơn độ lệch seed (0,004–0,008), nên có **dấu hiệu** clean hơi kém, nhưng 2 seed và 100 ảnh test không đủ để khẳng định. Chắc chắn một điều: **clean không tốt hơn raw** trong thí nghiệm này. Gần như toàn bộ chênh lệch đến từ **truck**: ba lớp còn lại lệch ≤ 0,01.

**Giả thuyết và cách kiểm:**

1. **Lớp truck quá ít nên rất nhiễu.** Test chỉ có 24 box truck, train `clean` 41 box (raw 32): một box truck đoán đúng/sai đổi AP truck vài điểm. Bằng chứng: riêng `clean`, AP truck giữa 2 seed đã chênh 0,10 (0,590 và 0,486). _Kiểm:_ chạy thêm 3–5 seed và báo độ lệch theo lớp; hoặc gộp truck/bus/car để xem phần còn lại có đổi không.
2. **Nhãn car/truck/bus trong clean vẫn lẫn.** Chỉ 80/202 ảnh được người duyệt; 122 ảnh còn nhãn máy. Người đã đổi lớp qua lại car↔truck↔bus ở các ảnh duyệt (`img_0078`, `img_0220`: car→truck; `img_0024`, `img_0124`: truck→car; `img_0083`, `img_0160`: bus→truck), nên trong clean một số "truck" là nhãn người, số khác là nhãn máy: lớp truck bị huấn luyện với hai tiêu chuẩn. _Kiểm:_ train biến thể chỉ gồm 80 ảnh đã duyệt (hoặc biến thể `oracle` của notebook) và so AP truck.
3. **Rò rỉ test làm `raw` được thổi phồng.** Pipeline phát hiện 5 ảnh `raw` trùng ảnh test (`LEAK_TEST`: `img_0049`~`test_033`, `img_0101`~`test_039`, `img_0167`~`test_044`, `img_0174`~`test_085`, `img_0221`~`test_009`): `raw` đã thấy 5% tập test khi train, `clean` thì không. Nhưng 5 ảnh test này chỉ có 1/24 box truck (`test_085`), nên rò rỉ giải thích được một phần nhỏ chênh mAP chung, **không** giải thích được việc truck giảm 0,11. _Kiểm:_ đánh giá lại cả hai model trên 95 ảnh test còn lại (bỏ 5 ảnh rò rỉ).
4. **Clean ít ảnh hơn** (202 so với 224, bỏ 12 ảnh trùng + 5 ảnh rò rỉ + 5 ảnh hỏng/nhỏ). Ultralytics tự bỏ ảnh hỏng và dòng nhãn lỗi của `raw` khi load, nên số ảnh `raw` thực sự dùng < 224. _Kiểm:_ đọc cảnh báo Ultralytics ở ô train của notebook để biết số ảnh/nhãn `raw` bị bỏ.

**Việc tiếp theo:** thêm seed (≥ 5) trước khi kết luận; đánh giá trên test bỏ 5 ảnh rò rỉ; duyệt hết 38 ảnh còn cảnh báo (để export thành Release) rồi train lại; ưu tiên duyệt các ảnh có truck/bus vì đây là lớp nhạy nhất.

## 6. Quyết định và ghi chú AI

**(a) Quyết định: HOLD.** Dataset dùng được để **thử nghiệm** (đã xuất bản nháp), chưa phát hành. Điều kiện để thành **Release**: số ảnh còn cảnh báo chưa duyệt ≤ 20/202 (< 10%), tức duyệt thêm **≥ 18 trong 38** ảnh còn cảnh báo (ưu tiên 16 ảnh `LOOSE_BOX`, 11 ảnh `FALSE_POS`) và xử lý cặp trùng `img_0084`~`img_0074`, **không** bằng cách nâng `conf`. Nếu lần duyệt sau để lại lỗi bắt buộc (vd. ảnh thiếu nhãn chưa gán) thì kết luận chuyển **Rework** và không xuất.

**(b) Dùng AI: có** (Claude Code).

- _Prompt chính:_ "phân tích dữ liệu các labeling và viết 4 module"; AI đọc docstring + test của từng module (đầu vào/đầu ra, quy tắc, ca biên, lệnh test) rồi viết `label_format` → `gate` → `autofix` → `second_opinion`, chạy pytest sau mỗi module.
- _Cách kiểm:_ `pytest` 79/79; thêm 5 ca biên tự viết (dòng dính 2 lỗi + dòng trống, clip rồi chạy lại phải idempotent, ảnh nhiều dự đoán, lỗi `data.yaml` → Rework, `data.yaml` hỏng cú pháp); đối chiếu `03_fixes.csv` với số lỗi v1 (20 + 8 + 6 + 1 = 35); mở xem bằng mắt các cặp ảnh bị coi là trùng.
- _Một lần AI sai:_ bản đầu của `autofix._rename_classes` gọi lại `ds.yaml_names()`, hàm này ném lỗi nếu `data.yaml` hỏng cú pháp → pipeline chết. Test đề không bắt được; phát hiện khi đọc lại code, sửa thành đọc YAML một lần trong `try/except` và dựng lại `names`.

**CVAT : lọc `width < 20`.** CVAT tự cài (Docker, `localhost:8080`). Project tạo từ `cvat/labels.json`; file đề để `"values": []` cho checkbox `can_review` nên CVAT báo lỗi, phải sửa thành `"values": ["false"]`. Task gồm 21 ảnh (20 ảnh đầu `05_review_queue.csv` + `img_0161`), nhãn sau duyệt (`work/run/ds`) import dạng YOLO 1.1.

- Bộ lọc `width < 20` (ảnh chụp trong `submission/cvat/`): `img_0020` **3 box**, `img_0030` **3 box**, `img_0135` **2 box**, `img_0161` **3 box** (CVAT hiện `11.4x43.8px`, khớp dòng 3 của nhãn). Tính từ file nhãn, bộ lọc còn khớp `img_0053` (1 box, không chụp) → tổng **12 box / 5 ảnh**, tất cả là `person`.
- **Đối chiếu `BOX_TINY`:** chỉ **3/12** box trùng — `img_0161` dòng 2, 3, 4 (rộng 10,3–11,9 px) có trong `07_error_list_v3` là `BOX_TINY`. 9 box còn lại là người đứng xa, rộng 15–19 px nhưng cao 36–75 px: vật thật, gán đúng. Khác biệt do ngưỡng: pipeline cờ khi **cạnh ngắn < 12 px** (quy tắc dự án), slide lọc **chiều rộng < 20 px** → 20 px theo chiều rộng cờ nhầm người đứng xa, còn chỉ xét `width` sẽ bỏ sót box bè thấp (cao < 12 px) mà `BOX_TINY` bắt.
- **`can_review`:** người gán bật thuộc tính này khi không chắc (vật bị che, bị mép ảnh cắt, khó phân biệt truck/car) để chuyển box cho người kiểm; mọi box import đều `can_review: false` vì nhãn YOLO không mang thuộc tính. Pipeline làm việc tương tự bằng cảnh báo WARN (`POSSIBLE_*`, `BOX_TINY`, `BOX_ASPECT_*`) dồn vào `05_review_queue.csv` theo trọng số, thay vì để người gán tự đánh dấu.

## check mới `box_aspect` (tỉ lệ khung hình box)

`pipeline/checks/box_aspect.py` + `tests/test_box_aspect.py` (13 test: đo theo pixel chứ không theo toạ độ chuẩn hoá, thống kê gộp toàn dataset, mỗi box tối đa 1 cờ, dòng hỏng/dòng trống, box tí hon bị bỏ qua, MAD = 0 không chia cho 0, ngưỡng lấy từ `cfg`, CLI). Hai cảnh báo (WARN): `BOX_ASPECT_EXTREME` khi rộng/cao (px) lệch quá `max_ratio` = 8 lần (box "sợi chỉ"); `BOX_ASPECT_CLASS` khi tỉ lệ lệch khỏi trung vị của lớp quá `z_thresh` = 3,5 độ phân tán "bền" (1,4826 × MAD của log tỉ lệ), chỉ với lớp có ≥ 20 box đủ lớn.
Vì `pipeline/checks/__init__.py`, `run.py` và `configs/pipeline.yaml` bị ghim, check chạy **riêng** (`python -m pipeline.checks.box_aspect --data work/run/ds --out submission/reports/extra_box_aspect`), đọc `cfg["box_aspect"]` nếu có, không thì dùng `DEFAULTS` trong module; nó **không** ảnh hưởng gate (kết luận vẫn Hold).

Kết quả (đo thực, không chỉnh ngưỡng theo raw):

- Trên dataset sau duyệt (202 ảnh): **7 cờ / 7 ảnh** (`extra_box_aspect.txt`). Mở xem cả 7: **6 là vật bị mép ảnh cắt** (`img_0042`, `img_0124`: sợi chỉ ở mép; `img_0073`, `img_0140`, `img_0148`, `img_0159`) — đáng cho người xem theo guideline "có gán vật bị cắt không"; **1 là box đúng** (`img_0160`: xe tải kéo moóc nhìn ngang, rộng/cao 3,8). **0 cờ là nhầm lớp.**
- Trên calib: z = 3,5 → 0 cờ; z = 2,5 → 2 cờ, cả 2 trúng lỗi `WRONG_CLASS` chèn (2/6). Trên raw trước duyệt: z = 3,0 trúng 2/22 box mà người đã đổi lớp, và cả 2 ảnh đó đều đã có `POSSIBLE_WRONG_CLASS`.
- **Vì sao yếu với nhầm lớp:** phân bố rộng/cao của car (trung vị 1,51; p10–p90: 0,75–2,83), truck (1,30; 0,73–2,09) và bus (1,37; 0,77–2,40) gần như trùng nhau, nên hình dạng box **không thể** tách car↔truck↔bus; car↔person chồng lấn một phần (person p90 = 1,07). Giá trị thực của check là tìm **box sợi chỉ / vật bị cắt mép**, bổ sung cho `BOX_TINY` và `clip_box`, chứ không thay được `second_opinion`.
