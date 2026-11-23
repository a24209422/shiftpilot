# 回答分數 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** agent／jev 評測多存最後的回答，並加上字串比對（B）與 LLM 評審（C）兩個回答分數，跟現有 SQL 分數並列。

**Architecture:** `evals/answer_match.py` 是純函式的字串比對；`evaluateCase` 把回答、B 的結果與所有標準答案存進每題結果。`evals/judge.py` 負責評審：可以在 `python -m evals.run --judge 模型` 時跟著跑完評審，也可以用 `python -m evals.judge 結果檔 --judge 模型` 對已存的 dev 結果重新評審。

**Tech Stack:** Python 3、pytest、既有的 `llm.callModel`

**Spec:** `docs/superpowers/specs/2026-11-23-qa-answer-score-design.md`

## 計畫對設計的修正

設計寫「評審是另一步，讀結果檔」。但 test 的結果檔刻意只存總分（`run.runCases` 會刪掉 `results`），事後沒有回答可以評審。所以：
- **test**：只能在評測當下用 `--judge` 跑評審，存檔一樣只留總分。
- **dev**：除了 `--judge`，也能用 `python -m evals.judge` 對已存的結果檔重新評審，調評審 prompt 時不用重跑 Haiku。設計裡「不用重跑」的目的，在 dev 上仍然成立。

## Global Constraints

- 縮排 2 個空白；變數與函式用 camelCase；註解用正體中文，只說明「為什麼」。
- 不改 `evals/scoring.py`、SQL 分數的判定，也不改任何問答 prompt、工具說明、`jevCriteria`。
- test 只印總分：不印、也不存 test 的逐題回答、評審理由、不一致清單。我不打開 `evals/heldout_cases.py` 和 `evals/results/test-*`。
- 評審模型：`google/gemini-3.5-flash-lite`（已在 `listModels()` 裡，經 OpenRouter），溫度 0（`llm.callModel` 已固定）。
- 評審 prompt 在 dev 上確定後就固定，跑 test 前不能再改。
- 呼叫 Haiku 或評審前，先估價並取得使用者同意。
- 從 `feature/jev-routing` 開分支 `feature/qa-answer-score`；不推送。

## Review Focus

1. 模型連不上（`outcome="unavailable"`，`answer` 是 None）：B 是 None、不跑評審，兩種回答分數都不計分。→ Task 2 `testUnavailableHasNoAnswerScore`、Task 3 `testJudgeSkipsMissingAnswer`
2. 評審在 JSON 前後多寫字，或根本不是 JSON：取第一個 `{...}` 解析，失敗才記 `judgeFailed`。→ Task 3 `testParseVerdictWithSurroundingText`、`testParseVerdictGarbage`
3. 評審連不上（`LlmUnavailableError`）：記 `judgeUnavailable`，整輪繼續跑。→ Task 3 `testJudgeUnavailableContinues`
4. test 加上 `--judge`：畫面只多兩個總分，存檔沒有 `results`、評審理由、不一致清單。→ Task 3 `testHiddenSplitJudgeLeaksNothing`
5. 數字誤判：標準答案 `1`，不能因為回答裡有「11/17」就算對。→ Task 1 `testNumberNeedsBoundary`

---

### Task 1: 字串比對（B）

**Files:**
- Create: `backend/evals/answer_match.py`
- Test: `backend/tests/evals/test_answer_match.py`

**Interfaces:**
- Produces: `matchAnswer(answer: str | None, goldResults: list[list[list]]) -> bool | None`。`answer` 是 None 時回傳 None。只要任一組標準答案的每個值都出現在回答裡，就回傳 True。

**規則**（照設計）：
- 數字：`3.20`、`3.2`、`Decimal("3.2")` 都當成 `3.2`；`68.0` 當成 `68`。比對時前後不能緊接數字或小數點。
- 日期（`date`，或 `YYYY-MM-DD` 字串）：接受 `2026-11-17`、`11/17`、`11 月 17 日`、`11月17日`；月、日不補 0。
- 日期時間（`datetime`，或 `YYYY-MM-DDTHH:MM:SS` 字串）：日期要符合上面的寫法，而且時間要出現 `10:00`、`10 點` 或 `10點` 其中一種。**這是我的決定**，設計沒有規定日期時間怎麼比。
- 文字：去掉前後空白後，直接找子字串。
- true、false、None 不比對。
- 標準答案是空的（`[]`）：回答裡有「查無」或「沒有」就算對。

- [ ] **Step 1: 寫會失敗的測試**

```python
def testNoneAnswer():          assert matchAnswer(None, [[["工程部"]]]) is None
def testNamesAllPresent():     assert matchAnswer("有陳大文、林小美", [[["陳大文"], ["林小美"]]]) is True
def testMissingName():         assert matchAnswer("只有陳大文", [[["陳大文"], ["林小美"]]]) is False
def testAnyAlternative():      assert matchAnswer("共 2 場", [[[3]], [[2]]]) is True
def testNumberNormalized():    assert matchAnswer("平均 3.2 人", [[[Decimal("3.20")]]]) is True
def testWholeFloat():          assert matchAnswer("工程部 68 小時", [[["工程部", 68.0]]]) is True
def testNumberNeedsBoundary(): assert matchAnswer("11/17 有會議", [[[1]]]) is False
def testDateForms():           # "2026-11-17" 對上 "11/17"、"11 月 17 日"、"11月17日"、"2026-11-17" 都是 True
def testDateTimeNeedsTime():   # "2026-11-24T10:00:00"：回答 "11/24 10:00" True、"11/24" False
def testSkipsNoneAndBool():    assert matchAnswer("林小美請假", [[["林小美", None, True]]]) is True
def testEmptyGold():           # [[]] 對上 "查無資料"、"這週沒有人請假" 為 True；"有 3 筆" 為 False
```

- [ ] **Step 2: 執行，確認失敗**

Run: `cd backend; python -m pytest tests/evals/test_answer_match.py -q`
Expected: FAIL（`ModuleNotFoundError: evals.answer_match`）

- [ ] **Step 3: 實作 `answer_match.py`**：用 `valueForms(value) -> list[list[str]] | None` 把一個值轉成「每一組都要出現、組內任一種寫法即可」的條件；None 代表不比對。數字用 regex `(?<![\d.])3\.2(?![\d.])`。

- [ ] **Step 4: 執行，確認通過**

Run: `cd backend; python -m pytest tests/evals/test_answer_match.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/evals/answer_match.py backend/tests/evals/test_answer_match.py docs/superpowers/specs/2026-11-23-qa-answer-score-design.md docs/superpowers/plans/2026-11-23-qa-answer-score.md
git commit -m "評測：新增回答的字串比對"
```

---

### Task 2: 評測存下回答與字串比對結果

**Files:**
- Modify: `backend/evals/run.py`（`evaluateCase`、`summarize`、`runCases` 的總結輸出）
- Test: `backend/tests/evals/test_run.py`

**Interfaces:**
- Consumes: `answer_match.matchAnswer`
- Produces: `evaluateCase` 的每題結果多三個 key：`answer: str | None`（`service.ask` 回傳的 `answer`，只在 agent／jev 模式；pipeline 一律 None）、`answerMatch: bool | None`、`goldAll: list[list[list]]`（所有可接受的標準答案）。`summarize` 多兩個 key：`answerMatchCorrect: int`、`answerMatchScored: int`（`answerMatch` 不是 None 的題數）。

- [ ] **Step 1: 寫會失敗的測試**（沿用 `test_run.py` 的 `world` fixture 與假 `toolLlm`）

```python
def testAgentResultKeepsAnswer(world):        # agent 模式假模型最後回 "工程部有陳大文" → result["answer"] == "工程部有陳大文"、result["answerMatch"] 是 bool、result["goldAll"] 是 list
def testPipelineHasNoAnswer(world):           # pipeline → result["answer"] is None、result["answerMatch"] is None
def testUnavailableHasNoAnswerScore(world):   # toolLlm 丟 LlmUnavailableError → outcome "unavailable"、answer 與 answerMatch 是 None
def testSummaryCountsAnswerMatch():           # 3 題 answerMatch 為 True、False、None → answerMatchCorrect == 1、answerMatchScored == 2
def testHiddenSplitPrintsAnswerMatchTotal(world, capsys):  # test split 只多印一行「回答（字串比對）：x/y」，不印 answer
```

- [ ] **Step 2: 執行，確認失敗**

Run: `cd backend; python -m pytest tests/evals/test_run.py -q -k "Answer or answer"`
Expected: FAIL（KeyError `answer` 或斷言不符）

- [ ] **Step 3: 實作**：`evaluateCase` 在 agent／jev 成功時取 `answer.get("answer")` 算 `matchAnswer`；總結 dev 與 test 都多印一行 `回答（字串比對）：{answerMatchCorrect}/{answerMatchScored}`。test 存檔照舊只留總分欄位，新的兩個計數可以留。

- [ ] **Step 4: 執行，確認通過**

Run: `cd backend; python -m pytest tests/evals/test_run.py tests/evals/test_answer_match.py -q`
Expected: 全部 PASS（原有測試不能壞）

- [ ] **Step 5: Commit**

```bash
git add backend/evals/run.py backend/tests/evals/test_run.py
git commit -m "評測：每題存下最後的回答與字串比對結果"
```

---

### Task 3: LLM 評審（C）

**Files:**
- Create: `backend/evals/judge.py`
- Modify: `backend/evals/run.py`（`main` 加 `--judge`；`runCases` 跑完各題後評審）
- Test: `backend/tests/evals/test_judge.py`

**Interfaces:**
- Consumes: Task 2 的 `answer`、`goldAll`、`answerMatch`；`llm.callModel(model, messages) -> str`、`llm.LlmUnavailableError`
- Produces:
  - `buildJudgeMessages(question: str, goldAll: list, answer: str) -> list[dict]`
  - `parseVerdict(text: str) -> dict`：`{"verdict": "correct" | "wrong", "reason": str}`，壞掉時 `{"verdict": "judgeFailed", "reason": ""}`
  - `judgeResults(results: list[dict], questions: dict[str, str], judgeModel: str, callJudge=llm.callModel) -> None`：直接在每題結果寫入 `judge`（上面的 dict）；`answer` 是 None 的題目不呼叫、`judge` 設 None；連不上時 `{"verdict": "judgeUnavailable", "reason": ""}`
  - `summarizeJudge(results) -> dict`：`judgeCorrect`、`judgeScored`（只算 correct 與 wrong）、`judgeFailed`、`judgeUnavailable`
  - `listDisagreements(results) -> list[dict]`：SQL 是否正確、`answerMatch`、評審是否判對，三者不全一樣的題目（None 的那一項不參與比較）；每筆有 `id`、`sql`（bool）、`answerMatch`、`judge`、`answer`、`reason`
  - `run.main` 新增 `--judge 模型`：只能搭配 `--mode agent` 或 `jev`，模型要在 `listModels()` 裡；summary 多 `judgeModel` 與 `summarizeJudge` 的欄位
  - `python -m evals.judge 結果檔 --judge 模型`：只接受 `split == "dev"` 而且有 `results` 的檔案；題目文字從 `evals.cases` 依 id 取；另存成 `<原檔名>-judged-<模型安全名>.json`

**評審 prompt 必須寫到的事**（確切寫法由實作決定，dev 確定後就固定）：用正體中文；附上問題、所有可接受的標準答案（JSON）和回答；判斷回答有沒有答到問題，多講不算錯，但多講的內容跟標準答案矛盾就算錯；標準答案裡的 null 代表提問者沒權限看，回答說不出細節也算對；標準答案是空的，代表應該回答查無資料；只輸出 `{"verdict": "correct" 或 "wrong", "reason": "一句話"}`。

- [ ] **Step 1: 寫會失敗的測試**（假的 `callJudge`，不連網路）

```python
def testParseVerdict():                     # '{"verdict": "correct", "reason": "有答到"}' → correct
def testParseVerdictWithSurroundingText():  # '```json\n{"verdict": "wrong", "reason": "x"}\n```' → wrong
def testParseVerdictGarbage():              # '我覺得對' 與 '{"verdict": "maybe"}' → judgeFailed
def testJudgeMessagesContainInputs():       # messages 裡有問題、"工程部"、回答文字
def testJudgeSkipsMissingAnswer():          # answer None → callJudge 沒被呼叫、judge is None
def testJudgeUnavailableContinues():        # 第一題丟 LlmUnavailableError、第二題正常 → judgeUnavailable、correct
def testSummarizeJudge():                   # correct、wrong、judgeFailed、None → judgeCorrect 1、judgeScored 2、judgeFailed 1
def testListDisagreements():                # SQL 錯、answerMatch True、judge correct → 列出；三者都對 → 不列
def testJudgeFlagNeedsAgentMode():          # main(["--split","dev","--judge","google/gemini-3.5-flash-lite"]) 為 pipeline → parser.error
def testHiddenSplitJudgeLeaksNothing(world, capsys, monkeypatch):  # test split + 假評審：輸出沒有回答與理由，存檔沒有 results、disagreements
def testStandaloneRejectsTestFile(tmp_path):  # split 是 test 的檔案 → SystemExit 1
def testStandaloneWritesJudgedFile(tmp_path, monkeypatch):  # dev 檔、假評審 → 新檔有每題 judge 與 judgeCorrect
```

- [ ] **Step 2: 執行，確認失敗**

Run: `cd backend; python -m pytest tests/evals/test_judge.py -q`
Expected: FAIL（`ModuleNotFoundError: evals.judge`）

- [ ] **Step 3: 實作 `judge.py` 與 `run.py` 的 `--judge`**：`runCases` 跑完所有題目後、存檔前呼叫 `judgeResults`；問題文字用 `{case["id"]: case["question"] for case in selected}`。dev 印出 `回答（評審）：x/y（格式壞掉 a 題、連不上 b 題）` 和不一致清單（每題一行：題號、三個 ✅／❌／－，接著縮排印回答與理由）；test 只印總分那一行。

- [ ] **Step 4: 執行，確認通過**

Run: `cd backend; python -m pytest tests/evals -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/evals/judge.py backend/evals/run.py backend/tests/evals/test_judge.py
git commit -m "評測：新增 LLM 評審的回答分數"
```

---

### Task 4: 跑 dev、確認評審、跑 test、更新 README

**Files:**
- Modify: `README.md`（「agent vs agent＋Jev」那一節）
- Modify: `docs/superpowers/specs/2026-11-23-qa-answer-score-design.md`（新增「實測紀錄」）

- [ ] **Step 1: 估價並取得同意**：Haiku 4 次評測約 US$0.10（README 花費表）。評審：用 `buildJudgeMessages` 對 dev 40 題算出字數，換算 token，乘上 OpenRouter 頁面上 `google/gemini-3.5-flash-lite` 的價格，估出 4 輪的費用。一起告訴使用者，同意後才跑。

- [ ] **Step 2: 跑 dev（jev、agent）**

Run: `cd backend; python -m evals.run --split dev --mode jev --model anthropic/claude-haiku-5.5 --judge google/gemini-3.5-flash-lite`，接著把 `--mode` 換成 `agent` 再跑一次
Expected: 各印出 SQL、字串比對、評審三個分數與不一致清單

- [ ] **Step 3: 請使用者人工確認不一致的題目**：把兩次的不一致清單整理成表格（題號、問題、標準答案、回答、三種判斷），請使用者標對或錯。依結果算出評審在這些題目上的正確率，寫進「實測紀錄」。如果評審明顯判錯，就調整評審 prompt，用 `python -m evals.judge <結果檔> --judge google/gemini-3.5-flash-lite` 重新評審。最多調 3 版，每版都記錄。

- [ ] **Step 4: 固定評審 prompt 並 commit**

```bash
git add backend/evals/judge.py docs/superpowers/specs/2026-11-23-qa-answer-score-design.md
git commit -m "評測：固定評審 prompt，記錄 dev 實測"
```

- [ ] **Step 5: 跑 test（jev、agent），只看總分**

Run: `cd backend; python -m evals.run --split test --mode jev --model anthropic/claude-haiku-5.5 --judge google/gemini-3.5-flash-lite`，接著換 `agent` 再跑一次
Expected: 只印進度與三個總分

- [ ] **Step 6: 更新 README**：新增一張表，列出 Haiku jev 與 agent 在 dev、test 的三種分數；寫一段結論，說明 SQL 分數有沒有低估模型、評審跟人工判斷差多少。

- [ ] **Step 7: Commit**

```bash
git add README.md docs/superpowers/specs/2026-11-23-qa-answer-score-design.md
git commit -m "README：回答分數的實測結果"
```
