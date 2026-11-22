# 請假排班系統

員工請假與排班的內部系統。目前有組織（部門、員工、行事曆）、資源預約（會議室、設備、公務車，同一資源同一時段不會被重複預約）、登入與角色、稽核紀錄；請假與排班模組之後再加。

## 啟動

需要 Docker。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }   # 已經有 .env 就不要蓋掉；新的 .env 要把兩組 change-me 密碼改成自己的值（只用英文和數字）
docker compose up -d --build --wait        # 第一次要建置映像檔；第一次建立資料庫可能要好幾分鐘
docker compose exec app python -m app.cli createUser --email admin@example.com --role admin   # 建立第一個管理員，會互動輸入兩次密碼
docker compose exec app python -m app.cli seedDemo                                            # 選用：示範的部門、員工、資源、排程
```

打開 <http://127.0.0.1:8000/>，用剛建的管理員登入。

- 只綁 `127.0.0.1`：目前沒有 HTTPS，不能對區網或外網開放。
- 更新程式後再執行一次 `docker compose up -d --build --wait`，資料庫遷移會自動套用，資料不會被清掉。
- **啟動失敗**：`--wait` 會回報 unhealthy；看原因用 `docker compose logs app`。不加 `--wait` 的話，失敗時容器只會不斷重啟，畫面不會有提示。
- 如果資料庫裡還有**舊版**（Streamlit）的資料表，遷移會因為名稱撞名而失敗，要先 `docker compose down -v` 清掉資料庫（會刪除所有資料；舊版只有示範資料）。
- 容器與手動啟動的 uvicorn 都用 8000，同時只能跑一個。要改 port，在 `.env` 加上 `APP_PORT`、`POSTGRES_PORT`（見 `.env.example`）。
- 時間用台灣時間（容器的 `TZ=Asia/Taipei`）。
- 停止：`docker compose stop`；連資料庫一起清掉：`docker compose down -v`（會刪除所有資料）。

## 問答

右側面板可以用中文問組織、會議、請假與班表。模型寫的 SQL 只在沙盒帳號 `qa_sandbox` 的連線上執行，它讀不到任何真實資料表，只看得到每題複製進去、提問者有權看的資料（今天前後各 90 天）。

1. `.env` 設定 `QA_DB_PASSWORD`（只用英文和數字）。新的資料庫第一次啟動時會自動建立帳號；**現有的資料庫**要執行一次：

   ```powershell
   docker compose up -d --wait postgres
   docker compose exec -T postgres sh /docker-entrypoint-initdb.d/02-create-qa-user.sh
   ```

   這個 script 每次都會把帳號密碼重設成 `.env` 的 `QA_DB_PASSWORD`（改密碼後重跑即可同步），也會替帳號關掉 `track_activities` 與 `track_counts`（避免不同提問者從 `pg_stat_activity` 看到彼此的 SQL）；較早建立帳號的資料庫重跑一次即可套用。

2. 本機開好 Ollama，下載 `.env` 的 `OLLAMA_MODEL`（例如 `ollama pull qwen2.5:3b`）。
3. `docker compose up -d --build --wait`。

已知限制：沙盒帳號仍讀得到資料庫的中繼資料（真實資料表的列數統計、函式原始碼），但讀不到任何資料列。

沒設定 `QA_DB_PASSWORD` 時問答會停用，其他功能照常。用雲端模型時（`OPENROUTER_API_KEY`、`GOOGLE_AI_API_KEY`），問題與查詢結果會送到廠商。

同時最多處理 3 題、每人同時 1 題，滿了會直接回「忙碌中」（不排隊），避免慢的問答占滿執行緒、拖慢其他功能。上限在 `backend/app/modules/qa/service.py` 的 `maxConcurrentQuestions`；名額記在記憶體裡，只在單一 uvicorn worker 下有效。

## 問答準確率

評測集在 `backend/evals/`：固定的公司資料（「現在」固定在 2026-11-17 星期二 14:30）、dev 40 題、test 25 題，每題指定提問者（一般員工、主管或人資）。比的是模型 SQL 跟標準答案 SQL 的執行結果；test 題由另一個 agent 出題後凍結，調整 prompt 時只看 dev，test 只看總分。

| 模型 | dev | test |
|---|---|---|
| qwen2.5:3b | 20/40 | 7/25 |
| qwen3-vl:4b-instruct | 未量 | 未量 |

（2026-11-21 起點分數，沒有改過任何 prompt。dev 各類別：組織 3/5、班表 4/8、誰有空 1/7、請假 6/8、會議 3/7、統計 3/5。）

執行（在 `backend/`，需要本機 Ollama；dev 約 5～10 分鐘（3b））：

    python -m evals.run --split dev
    python -m evals.run --split test --model qwen3-vl:4b-instruct
    python -m evals.run --split dev --filter shift
    python -m evals.run --split dev --mode agent

`--mode agent` 改用 tool calling（見下一節），結果檔名會帶模式（`dev-agent-…`、`dev-pipeline-…`）。4b 約需 3 GB 記憶體，要在終端機執行並先關掉其他程式。

改了固定資料或沙盒邏輯導致標準答案改變時，執行器會停下並列出題號；確認改變是預期的，才執行 `python -m evals.run --split dev --update-snapshot` 或 `python -m evals.run --split test --update-snapshot`。

已知限制：問答服務沒有告訴模型提問者是誰，所以評測題都用指名問法，量不到「我的假」這類問法。

### 舊流程 vs agent（tool calling）

agent 模式讓模型自己呼叫三個工具：`run_sql`（沿用 SQL 檢查與沙盒）、`find_available_people`（誰有空，程式算）、`get_busy_periods`（某人或某資源的會議與請假），最多 4 次工具呼叫。工具都在同一個沙盒裡執行，看到的資料跟舊流程一樣已依提問者過濾。API 用 body 的 `mode` 或環境變數 `QA_MODE` 切換，預設舊流程；問答面板可以切換並展開工具步驟。

| qwen2.5:3b | dev | 誰有空 | test | 平均秒數 | 平均工具呼叫 |
|---|---|---|---|---|---|
| 舊流程 | 20/40 | 1/7 | 7/25 | — | — |
| agent | 10/40 | 3/7 | 3/25 | 9.5 | 0.9 |

（2026-11-22，agent 第一版，沒有調整過工具說明或 prompt。dev 各類別：組織 0/5、班表 1/8、誰有空 3/7、請假 3/8、會議 0/7、統計 3/5。）

「誰有空」交給程式算確實有效，但整體掉了一半。dev 上看到的錯誤模式：

- **工具選錯**：`find_available_people` 被用了 12 次，大多用在不相關的題目，例如「工程部有哪些人？」也拿它來查
- **不會多步**：36 題只呼叫 1 次工具、4 題沒呼叫；工具回錯誤後，模型直接用文字收尾，沒有修正再試（舊流程有一次固定的重試）
- **班表題不用工具**：4 題班表題直接用文字回答
- **SQL 品質沒有 few-shot 幫忙**：例如 `employee_id = '林小美'`、`resources` 欄位寫錯

雲端模型（經 OpenRouter，agent 模式，2026-11-22）：

| agent 模式 | dev | 誰有空 | test | 平均秒數 | 平均工具呼叫 | 花費（dev + test，以 OpenRouter 頁面最高價估） |
|---|---|---|---|---|---|---|
| Claude Haiku 5.5 | 33/40 | 7/7 | 23/25 | 4.5 | 1.0 | 約 $0.05 |
| GPT-6 Luna | 33/36 | 5/5 | 22/23 | 5.2 | 1.1 | 約 $0.05 |

（Luna 有 dev 4 題、test 2 題連不上，不計分。雲端模型的舊流程分數還沒量。）

同一套工具，雲端模型每題幾乎都只呼叫一次工具就選對，所以 3b 的低分主要是模型能力，不是工具設計。兩個雲端模型剩下的錯誤集中在統計題（例如依天數分組計數）；Haiku 另外在請假題用 `get_busy_periods` 查，拿不到假別。

### agent vs agent＋Jev（決策模型選工具）

jev 模式在 agent 前面加一步：先問 Jev（TypeSafe 的決策模型，只回答事先定義的選項、不產生文字）「這題該用哪個工具」，再讓 LLM 只拿到被選中的那個工具去填參數。Jev 沒設定、信心低於 0.5、逾時或回應格式不對時，退回三個工具都給的 agent。要用先在 `.env` 填 `JEV_API_KEY`（見 `.env.example`），API 的 `mode` 設 `jev`，問答面板選「Agent＋Jev」。Jev 只看到問題文字、日期參考和三個選項的說明，看不到任何資料。

| 2026-11-22 | dev | 誰有空 | test | 平均秒數 | LLM 輸入 tokens（dev） | Jev tokens（dev） |
|---|---|---|---|---|---|---|
| qwen2.5:3b agent | 10/40 | 3/7 | 3/25 | 9.5 | 115,563 | — |
| qwen2.5:3b jev | 14/40 | 3/7 | 2/24 | 9.4 | 102,522 | 46,441 |
| Haiku 5.5 agent | 33/40 | 7/7 | 23/25 | 4.5 | 207,066 | — |
| Haiku 5.5 jev | 32/40 | 6/7 | 19/25 | 5.9 | 168,865 | 46,441 |

（3b jev 的 test 有 1 題模型連不上，不計分。3b 的 jev dev 是調整過一次 Jev 選項說明後的分數，調整前是 10/40；調整只看 dev，沒有看 test，所以 test 沒有跟著進步。）

**花費**：Haiku 以 OpenRouter 頁面最高價估（輸入 $0.11、輸出 $0.55／百萬 tokens），Jev 以第三方文章的 $0.042／百萬輸入 tokens 估，TypeSafe 官方沒公布價格，數字只能當量級。

| Haiku 5.5 | dev | test |
|---|---|---|
| agent | 約 $0.031 | 約 $0.021 |
| jev（LLM＋Jev） | 約 $0.026＋$0.002 | 約 $0.018＋$0.001 |

結論：**接 Jev 沒有讓問答變準，只省了一成左右的錢，而且比較慢**。
- 準確率：3b 的 dev 從 10 升到 14，但 test 沒動，仍低於舊流程的 7/25；Haiku 的 dev、test 都比 agent 低（test 差 4 題）。
- 省錢：LLM 只拿一個工具定義，輸入 tokens 少約 18%，但要多付 Jev 的費用，淨省約 10%。
- 速度：多一次 Jev 往返，每題慢約 1.4 秒（Haiku）。
- Jev 的選擇：dev 上 40 題的信心最低 0.49～0.55、約四分之三在 0.9 以上；0.5 的門檻只擋下 Haiku 那 1 題，其餘沒作用。選錯時 LLM 只有一個工具可用，沒有機會自己換，這是 Haiku test 掉分的可能原因，但我沒有看 test 的逐題結果，無法確認。
- 選項說明很重要：第一版把會議、請假的題目都丟給 `get_busy_periods`（21 題只對 1 題），但這個工具只回傳誰、起訖與標題，答不了假別、核准狀態、參加者；改成寫明它答不了的事之後，dev 從 10 升到 14。

## 開發

- 後端（FastAPI + PostgreSQL）：見 `backend/README.md`
- 前端（React + Vite）：見 `frontend/README.md`

```powershell
cd backend; python -m pytest -q; cd ..     # 需要先 docker compose up -d --wait postgres；約 6 分鐘
cd frontend; npm test; cd ..               # 不需要資料庫
```

## 目錄

| 路徑 | 內容 |
|---|---|
| `backend/` | API、資料庫遷移、指令列（建帳號、示範資料）、測試 |
| `frontend/` | 畫面 |
| `docker/` | PostgreSQL 第一次啟動時建立 app 帳號與資料庫的 script |
| `docs/superpowers/` | 設計文件（specs）與實作計畫（plans） |
| `prototype/` | 外觀原型（一次性，只當參考） |
| `legacy/` | 舊版 Streamlit + text2sql，不維護、不跑測試；之後做問答時可以回來參考 |

## 已知限制

- 稽核紀錄「只能新增」目前靠資料庫權限，應用程式的資料庫帳號自己仍能把權限加回來，要另一個擁有者角色才會真的鎖死。
- 登入失敗 5 次會鎖帳號 15 分鐘，目前沒有解鎖指令。
- 問答（text2sql）還沒做，畫面右側只有面板外殼。
