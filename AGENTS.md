# Agent Skill Lab — Hướng dẫn cho AI Agent

## Ranh giới sản phẩm

Agent Skill Lab là **CLI toolkit để đánh giá và debug AI Agent Skill**.

Agent Skill Lab không phải:
- Agent runtime
- AI Agent
- Agent Skill
- LLM
- Claude Code plugin
- Nền tảng chạy Agent production

Claude Code hiện chỉ là runtime đầu tiên được Agent Skill Lab hỗ trợ.

## Nguyên tắc kỹ thuật

- Luôn kiểm tra trạng thái thực tế của repo trước khi đề xuất thay đổi.
- Ưu tiên bằng chứng tất định hơn đánh giá bằng LLM.
- Không tuyên bố hành vi đã được xác minh nếu chưa có probe thực tế.
- Không vô hiệu hóa hoặc bypass gate của fixture/workspace.
- Tách biệt Actor, Trace và Evaluator.
- `replay --rescore` không được chạy Actor hoặc gây side effect.
- Không viết test chỉ để tăng coverage.
- Không tạo abstraction cho nhu cầu tương lai khi hiện tại chưa cần.
- Giữ dependency tối thiểu.
- Comment ngắn gọn, giải thích "tại sao", không mô tả lại code.

## Kiểm chứng thay đổi

Sau mỗi thay đổi:

1. Chạy các test liên quan.
2. Chạy toàn bộ test khi thay đổi ảnh hưởng core behavior.
3. Chạy `ruff`.
4. Với subprocess, hook, fixture, filesystem hoặc process lifecycle: phải có probe thực tế.
5. Báo cáo bằng chứng đo được, không suy đoán.

## Kỷ luật phạm vi

Không tự ý mở rộng Agent Skill Lab thành Agent platform.

Không triển khai thêm:
- Optimizer
- LLM Judge
- runtime adapter mới
- plugin

trừ khi được yêu cầu rõ ràng.

Ưu tiên hiện tại là độ tin cậy của Core và Claude Code integration.

---

## Nơi các nguyên tắc trên được cưỡng chế

Phần này không thêm luật. Nó chỉ trỏ tới chỗ luật đã thành code, để một phiên sau không phá vỡ
chúng vì không biết chúng ở đâu — và để mỗi lần sửa ở đó là một quyết định có ý thức.

| Nguyên tắc | Cưỡng chế ở đâu | Test giữ chỗ |
|---|---|---|
| Tách Actor / Trace / Evaluator | [`agent.py`](src/skill_lab/agent.py) · [`trace.py`](src/skill_lab/trace.py) · [`verify.py`](src/skill_lab/verify.py) | — |
| Trace không do agent tự khai | [`hooks/trace_hook.py`](src/skill_lab/hooks/trace_hook.py) (PreToolUse/PostToolUse) | `test_fixture_and_hook.py` |
| `--rescore` không chạy Actor, không side effect | `verify.ENVIRONMENT_CHECKS` + `VerifyContext.environment` | `test_check_moi_truong_khong_chay_subprocess_khi_fixture_da_mat` |
| Bằng chứng tất định trước LLM | `CheckResult.deterministic`; judge tách riêng | `test_measurement.py` |
| Không bypass gate | [`fixture.assert_gates`](src/skill_lab/fixture.py) → `FIXTURE_INVALID`, actor không khởi động | `test_gate_preservation.py` |
| Không tuyên bố quá bằng chứng | `Diagnosis.confidence`; `owner = unknown` khi không neo được | `test_khong_neo_duoc_vao_buoc_nao_thi_owner_la_unknown` |
| Dependency tối thiểu | `pyproject.toml`: đúng một (`pyyaml`) | — |

**Hai điều một phiên mới thường hiểu nhầm:**

1. **`judge.py` đã tồn tại.** "Không triển khai thêm LLM Judge" nghĩa là không mở rộng nó, không
   phải là chưa có. Nó chưa từng gọi model thật lần nào.
2. **`actor.cli` / `judge.cli` trong config chỉ đặt tên binary, không phải runtime adapter.**
   [`agent.py`](src/skill_lab/agent.py) dựng argv bằng cờ riêng của Claude Code
   (`--output-format json`, `--permission-mode`, `--max-turns`, `--effort`,
   `--append-system-prompt`). Đổi `cli:` sang thứ khác sẽ hỏng. Hỗ trợ runtime thứ hai là một
   việc phải làm có chủ ý, không phải một trường config đã sẵn sàng.
