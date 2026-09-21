# Skill Lab

Phòng thí nghiệm cho Agent Skill: chạy một skill trong môi trường cách ly, ghi lại toàn bộ
trajectory, chấm bằng các check tất định, chỉ ra **bước sai đầu tiên**, quy trách nhiệm **kèm độ
tin cậy**, và so sánh hai phiên bản mà không tự tuyên bố bên nào tốt hơn khi dữ liệu chưa nói được
điều đó.

Không phải một "skill tester". Câu hỏi nó trả lời không phải *skill này pass hay fail*, mà là:

- Agent hỏng ở **bước nào**?
- Lỗi thuộc về **Skill, Knowledge, Tool, Harness, Repository hay Model** — và **chắc đến đâu**?
- Sau khi sửa, kết quả có thật sự tốt lên, hay chỉ là nhiễu, hay là **chưa đo đủ để biết**?
- Cái đã tốt lên là **skill** hay là **model**?
- Có gì **đi lùi** không?

Nguyên tắc chi phối mọi quyết định trong repo này:

> Đừng làm Skill Lab thông minh hơn trước khi làm nó đo đúng hơn.

---

## Đây là cái gì — và không phải cái gì

**Một CLI tool viết bằng Python.** Cài bằng `pip`, chạy bằng `skill-lab <lệnh>`, và nó đo một
workspace *khác*.

| | |
|---|---|
| **Không phải một agent.** | Nó không có agent nào của riêng nó. [`agent.py`](src/skill_lab/agent.py) gọi `claude -p` như một subprocess — nó là **người tiêu thụ** một agent runtime. |
| **Không phải một Claude Code plugin.** | Không có gì để cài vào phiên của bạn. Giá trị nằm ở CLI. |
| **Không chứa skill nào.** | Skill nằm ở workspace **đích** — repo mà bạn trỏ `--workspace` vào. |

Quan hệ nó giả định:

```
repo này (công cụ)  ──đo──>  workspace của bạn (.claude/skills/ + cases/)
```

`tests/fixtures/demo-workspace/` là một workspace tí hon dùng cho demo và test. Nó ở trong
`tests/` chứ không ở gốc repo, đúng vì nó là **dữ liệu thử**, không phải thứ repo này cung cấp.

---

## Cài đặt

```bash
pip install -e .
```

Một dependency duy nhất (`pyyaml`), chỉ dùng để đọc case file. Kit này chạy bên trong fixture của
repo khác, nên mỗi dependency thêm vào là một thứ có thể xung đột với repo đó hoặc vắng mặt trong
CI của nó.

## Bắt đầu trên một workspace

```bash
cd <repo có .claude/skills/>
skill-lab init          # tạo skill-lab.yaml + cases/
skill-lab skills        # các skill tìm thấy, kèm hash phiên bản
skill-lab run <case>    # chạy thật (tốn tiền)
```

Thử ngay mà không tốn đồng nào, dùng workspace demo có sẵn:

```bash
skill-lab --workspace tests/fixtures/demo-workspace run tidy-pass --dry       # đạt
skill-lab --workspace tests/fixtures/demo-workspace run tidy-premature --dry  # hỏng có chủ ý
```

`skill-lab.yaml` là **thứ duy nhất kit này biết về workspace của bạn**. Không dòng code nào trong
package biết tên một repo cụ thể.

---

## Các lệnh

| Lệnh | Trả lời câu gì |
|---|---|
| `run <case>` | trạng thái từng check, điểm, trajectory, bước, chi phí, thời gian, chẩn đoán |
| `debug <run-id>` | bước sai đầu tiên, phân loại, độ tin cậy, bằng chứng, ai phải sửa |
| `compare <baseline> <candidate>` | độ chính xác, regression, chi phí, thời gian, **biến nào đã đổi** |
| `replay <run-id>` | chạy lại case đó · `--rescore` chấm lại miễn phí, không chạm môi trường |
| `matrix` | cùng dataset, nhiều `model/effort`, một bảng |
| `experiment <file>` | chạy một thí nghiệm đã khai báo — giả thuyết viết trước, kết quả sau |
| `list` / `cases` / `skills` | những gì đang có |

Trước mỗi lần chạy, `assert_gates` chứng minh môi trường còn đo được — xem *Fixture* bên dưới.

### `--dry`: chạy cả đường ống với chi phí bằng 0

Đặt một file `<case>.trace.jsonl` cạnh case file, và `--dry` phát lại nó thay vì gọi model. Toàn
bộ 89 test của kit đi qua đường này; không test nào gọi model.

---

## Sáu trạng thái của một check

`passed` một mình không đủ. Nó gộp "đỏ vì skill sai" với "không chấm được" và với "bằng chứng
yếu" — ba thứ đòi hỏi ba hành động khác hẳn nhau.

| Trạng thái | Nghĩa | Tính vào điểm? |
|---|---|---|
| `PASS` | đạt | có |
| `FAIL` | không đạt | không |
| `WEAK_EVIDENCE` | có bằng chứng, nhưng bằng chứng không chứng minh được điều cần chứng minh | không, đếm riêng |
| `NOT_APPLICABLE` | điều kiện của check không tồn tại trong lần chạy này | có (rỗng nghĩa) |
| `UNDECIDED` | thiếu dữ liệu để phán quyết | không, đếm riêng |
| `NOT_EVALUATED` | check cần môi trường sống, và môi trường đó không còn | không, đếm riêng |

Dòng điểm hiện cả ba nhóm sau: `diem: 5/7 check tat dinh xanh, 1 bang chung yeu, 2 khong do duoc`.
Một 8/8 trên một case có ba check không đo được thì không phải 8/8.

## Test case

```yaml
id: doc-rang-buoc-truoc-khi-ghi
skill: tidy-a-module
fixture: git-worktree
tags: [core]

task: |
  Module `model` có một hàm không còn ai gọi. Bỏ nó đi.

expect:
  must:
    - check: command_before_write
      command: ["make lint-rules"]
    - completed
  must_not:
    - check: tool_used
      tool: WebFetch
  evidence:
    required: true
    commands: ["make test"]   # gọi tên lệnh, xem bên dưới

budget:
  max_cost_usd: 1.50
  max_steps: 90
```

### Các check có sẵn

Nhóm **chỉ đọc trajectory** — tất định, chấm lại lúc nào cũng ra cùng kết quả:
`command_ran` · `command_order` · `command_before_write` · `delegated_to` · `no_broad_discovery` ·
`no_main_edit` · `no_gate_bypass` · `writes_confined` · `tool_used` · `evidence_backed` ·
`max_steps` · `max_cost_usd` · `max_duration_s` · `completed`

Nhóm **cần môi trường sống** — chỉ chấm được khi fixture còn: `file_exists` · `file_contains` ·
`shell`

Ranh giới này không phải phân loại cho đẹp. Nó là câu trả lời cho *"bộ chấm có tất định không"*:
nhóm trên có, nhóm dưới tất định đúng bằng mức thế giới bên ngoài tất định — và đó không phải một
tính chất kit này được phép hứa thay cho chúng.

### `evidence_backed`: bốn trạng thái, và tại sao

`git status` chạy sau lần ghi cuối **không** kiểm chứng gì cả. Trước khi có bốn trạng thái, một
`git status` như thế làm check này XANH — một false positive đã đo được.

- khai `commands:` → tìm đúng lệnh đó, chạy sau lần ghi cuối, kết quả quan sát được là thành công → `PASS`
- không khai `commands:` → có lệnh bất kỳ thành công → `WEAK_EVIDENCE`, và `why` nói thẳng lý do
- không có lần ghi nào → `NOT_APPLICABLE`
- trace không có dòng `tool_result` nào → `UNDECIDED`

**Luôn khai `commands` khi bạn biết lệnh kiểm chứng là gì.**

---

## Chẩn đoán: giả thuyết có độ tin cậy, không phải phán quyết

```
chan doan:
  buoc sai dau tien   2  (check `doc-rang-buoc-truoc-khi-ghi`)
  anh huong ve sau    2 buoc sau do khong con dang tin
  phan loai           repository.command_missing
  ai phai sua         repository
  do tin cay          medium
  da doi chu so huu   tu `verification` sang `repository.command_missing` vi trace noi khac
  bang chung
    - buoc 6 tra ve: make: command not found (o buoc 6, khong phai buoc sai dau tien)
  gia thuyet          Gia thuyet (medium): nguyen nhan nam o `repository` ...
```

**Bước sai đầu tiên được tính, không hỏi model.** Mỗi check thất bại đã biết chỉ số bước nơi nó
vỡ, nên bước sai đầu tiên là `min` của các chỉ số đó.

**Độ tin cậy đến từ độ neo của bằng chứng, không từ cảm giác:**

| | |
|---|---|
| `high` | bằng chứng nằm đúng tại bước sai đầu tiên |
| `medium` | bằng chứng ở chỗ khác nhưng liên quan trực tiếp tới check đã vỡ |
| `low` | không neo được vào bước nào, hoặc phán quyết đến từ judge → `owner = unknown` |

**Không phải thất bại nào cũng là lỗi của skill.** Nếu trace cho thấy agent đã làm đúng và môi
trường từ chối — một gate chặn, một lệnh không tồn tại, một trần turn cắt ngang — thì sửa skill để
cho xanh sẽ sinh ra một skill có **hai** lỗi thay vì một. Nhãn cũ luôn được giữ ở
`reattributed_from` để người đọc phản bác được thay vì phải tin.

---

## Identity của một thí nghiệm

Một lần chạy được xác định bởi:

```
skill_version · workspace_rev · case_digest · model · effort
              · harness_version · toolset_version · knowledge_revision
```

Ba trường cuối là chuỗi tự do và rỗng theo mặc định: phần lớn workspace không đánh phiên bản cho
harness hay bộ tool của mình, và một trường rỗng nói đúng sự thật đó.

`compare` đọc identity thật từ các lần chạy và **nói ra biến nào đã đổi**:

```
phep so nay do: confounded
bien da doi:
  skill_version       aaa  ->  bbb
  model               sonnet  ->  opus

ket luan: INSUFFICIENT_EVIDENCE
  - ca skill lan cau hinh chay deu doi giua hai ben -- khong tach duoc phan dong gop
```

Trước khi có phần này, một baseline Sonnet so với một candidate Opus vẫn được đọc như một cải
thiện của skill, và không dòng nào trong báo cáo nói rằng model đã đổi.

### Model matrix

```bash
skill-lab --workspace tests/fixtures/demo-workspace matrix --dataset demo
```

```
cau hinh              lan chay  ty le xanh   buoc tb  tool call    USD tb   giay tb
claude-opus-5/high          12      91.7%      14.2       11.0    0.8100      62.3
sonnet/medium               12      83.3%      18.6       15.4    0.2300      31.7
```

Mặc định: **bulk evaluation → Sonnet / medium**, **chẩn đoán khó → Opus 5 / high**. Check tất định
không cần model nào.

---

## Năm kết luận của `compare`

| Kết luận | Khi nào |
|---|---|
| `IMPROVED` | tỷ lệ xanh tăng vượt nhiễu, không regression, không vượt ngân sách |
| `REGRESSED` | có case từ luôn-xanh thành không-còn-luôn-xanh, hoặc case biên đi lùi, hoặc tỷ lệ giảm vượt nhiễu |
| `TRADE_OFF` | tốt lên thật, nhưng chi phí hoặc thời gian vượt ngưỡng |
| `NO_CLEAR_DIFFERENCE` | **đủ** dữ liệu để so, và hiệu nằm trong nhiễu |
| `INSUFFICIENT_EVIDENCE` | **không đủ** dữ liệu: quá ít lần chạy, không case chung, hoặc biến bị trộn |

Hai kết luận cuối khác nhau, và gộp chúng lại là cách một bộ so sánh nói *"không khác biệt"* trong
khi sự thật là *"chưa đo đủ để biết"*.

**Không kết luận nào là một quyết định promote.** `IMPROVED` nói rằng độ đo đã tăng và không có gì
đi lùi; nó không nói nên triển khai. Kit này không tự sửa skill và không tự promote.

## Thí nghiệm

```bash
skill-lab --workspace tests/fixtures/demo-workspace \n  experiment tests/fixtures/demo-workspace/experiments/rang-buoc-truoc-ghi.yaml
```

File thí nghiệm bắt bạn viết **giả thuyết trước khi thấy kết quả**, và khai biến nào đổi / biến
nào giữ. `compare` đọc identity thật rồi đối chiếu; hai bên lệch nhau là một phát hiện:

```
thiet ke khong khop voi thuc te:
  - `model` duoc khai la `fixed` nhung da doi
  Mot thi nghiem chay khac voi thiet ke cua no van cho ra so, va nhung so do tra loi mot cau
  hoi khac voi cau da dat.
```

---

## Replay: hai nghĩa, cả hai đều thật

```bash
skill-lab replay <run-id> --rescore   # trajectory đã có -> bộ chấm hiện tại. Không gọi model.
skill-lab replay <run-id>             # fixture mới, chạy actor lại. Một lần chạy MỚI.
```

`--rescore` **không chạm vào thế giới bên ngoài**: các check cần môi trường trả `NOT_EVALUATED`
thay vì chạy lệnh. Và nó chỉ tuyên bố tất định trên đúng phần nó có quyền:

```
khong cham lai duoc 1 check can fixture: kiem-build -- chay lai voi `--keep` neu can chung
bo cham tat dinh tren 6 check doc-trajectory: cham lai ra dung ket qua cu
```

`replay` (không cờ) dựng fixture mới và chạy lại — actor là một model, nên đây là một lần chạy
**mới**, so sánh được, không phải một bản sao. Kit không gọi nó là deterministic.

---

## Fixture giữ nguyên gate của workspace

Chi tiết dễ bỏ qua nhất và nó quyết định phép đo có nghĩa hay không. Nếu fixture làm các gate của
chính workspace ngừng hoạt động — vì thiếu một thư mục, vì package chưa cài — thì chúng vẫn có
mặt, vẫn chạy, và **không gác gì cả**. Lúc đó bộ đo không còn đo *"skill dẫn agent thế nào dưới áp
lực thật"*, nó đo *"agent làm gì khi không ai gác"*.

Hook của lab được **thêm vào** `.claude/settings.json` của fixture, không ghi đè. `fixture.setup`
khai những lệnh cần chạy để gate của workspace thực sự hoạt động bên trong fixture.

### `assert_gates`: chứng minh, không giả định

`setup` *làm cho* gate chạy được. `assert_gates` *chứng minh* rằng nó chạy được:

```yaml
fixture:
  strategy: git-worktree
  setup:
    - ["python", "-m", "pip", "install", "-e", "."]
  assert_gates:
    - name: ghi vào repo bị chặn khi chưa có lease
      command: ["python", "scripts/thu-ghi.py"]
      expected_exit: 2
    - command: ["make", "lint-rules"]
      expected_exit: 1
```

Thứ tự bắt buộc:

```
dựng fixture → cài workspace → merge hook của Lab → fixture.setup
             → assert_gates → CHỈ KHI TẤT CẢ ĐẠT → actor chạy
```

```
Gate preservation
  [OK  ] gate-cua-workspace
         mong doi exit: 1
         thuc te exit:  1
  [HONG] make protected-command
         mong doi exit: 1
         thuc te exit:  0

FIXTURE_INVALID
Actor KHONG duoc khoi dong -- moi truong nay khong do duoc dieu case yeu cau.
```

Bốn ràng buộc, mỗi cái vá một cách hỏng cụ thể:

1. **`expected_exit` bắt buộc, không có `must_fail: true`.** `exit 1`, `exit 2` và `exit 126` mang
   ba nghĩa khác nhau — một gate từ chối, một gate lỗi cấu hình, một file không chạy được. Một cờ
   nhị phân gộp cả ba, nên một gate **đã hỏng** sẽ qua được đúng như một gate **đang chạy**.
2. **Gate chạy bên trong fixture**, `cwd` là gốc fixture. Chạy trên host sẽ trả lời một câu hỏi về
   host, còn câu hỏi đang đặt là về chính môi trường actor sắp chạy trong đó.
3. **Assertion chỉ được quan sát.** Skill Lab chụp dấu vân tay `(đường dẫn, kích thước, mtime)` của
   cả fixture trước và sau khi chạy gate; nếu có gì đổi → `FIXTURE_INVALID` kèm danh sách file. Một
   assertion tự sửa fixture để mình xanh làm mọi con số sau đó nói về một môi trường khác.
4. **`FIXTURE_INVALID` là kết quả thứ ba**, không phải skill thất bại và không phải lỗi công cụ.
   Bản ghi mang `status: fixture_invalid`, chẩn đoán có `owner: harness`, không có check skill nào
   được chấm, và các bảng gộp bỏ qua nó.

Mã thoát: `0` đạt · `1` skill đỏ · `2` công cụ hỏng · `3` FIXTURE_INVALID. Một scheduled job phải
phân biệt được ba thứ cuối: chúng gửi cho ba người khác nhau.

---

## Giới hạn đã biết

- **Judge chưa từng gọi model thật.** Đường dựng prompt và đường phân tích có test; lần gọi thật
  thì chưa.
- **`--rescore` không dựng lại fixture**, nên check môi trường trả `NOT_EVALUATED` trừ khi lần chạy
  gốc dùng `--keep`.
- **Chưa có Optimizer, chưa có Skill mutation tự động, chưa có RL/SFT.** Có chủ ý.
- **Taxonomy cố ý nông.** Thêm một nhánh cần một trace, không phải một trực giác.
- **Nếu tiến trình `skill-lab` chết giữa chừng, actor bị mồ côi và chạy tiếp** mà không ai ghi kết
  quả. Bản ghi ở lại trạng thái `running`, và các bảng gộp bỏ qua nó — nhưng tiến trình vẫn tiêu
  token cho tới khi bị dừng bằng tay.
- **`num_steps` đếm cả dòng `tool_result`**, còn `num_tool_calls` chỉ đếm lời gọi. Đọc nhầm hai
  trường này sẽ ra hai con số khác nhau cho cùng một lần chạy.

## Đóng góp / sửa repo này

Ràng buộc dành cho người (và agent) sửa Skill Lab nằm ở **[`AGENTS.md`](AGENTS.md)**: ranh giới
sản phẩm, nguyên tắc kỹ thuật, cách kiểm chứng thay đổi, và kỷ luật phạm vi.

## Chạy test

```bash
pytest
```

89 test, không test nào gọi model. Mỗi lỗi từng tìm ra đều có một regression test, và test đó mở
đầu bằng câu mô tả điều đã đo được **trước khi** sửa.
