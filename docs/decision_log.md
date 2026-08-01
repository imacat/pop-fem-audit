# 決策日誌

每筆記錄：日期、決策、理由。定義檔（`prompts/`）、codebook、
研究計畫的任何修訂都必須在此留下記錄。

## 2026-07-30

- **語料擴大為 2016–2025 十年**（先導研究為 2018–2025）。
  理由：框架完整、可看年度趨勢。
- **全文不與先導研究比較**：論文僅呈現正式研究結果，數字
  一律以正式研究為準；先導研究只作為 codebook v0 與假說的
  內部來源，記於本日誌，不進入論文敘事。
- **分析管線採 API script，不用 Claude Code subagent**。理由：
  實測證實 subagent 會繼承 CLAUDE.md 與環境資訊，context 無法
  僅憑定義檔重現；API 呼叫的輸入完全受控且可稽核。
- **模型釘定 `claude-sonnet-4-6`、temperature=0、thinking 關閉**。
  理由：該組合非決定性最低；條件 A/B 盲點實驗以模型為研究
  對象，須與 pilot 的 Sonnet 家族銜接。Fable 5 不採用（成本、
  thinking 不可關閉且不可稽核、無 temperature、混淆核心主張）。
- **工具性環節的模型於階段 3 以校準樣本實測後決定**：同批
  校準樣本以 Sonnet 4.6 與 Opus 5 各跑一次，對照人工黃金標準
  比較一致率，據以決定是否於特定環節升級。
- **codebook 採 directed content analysis**：理論骨架
  （top-down）＋開放碼歸納通道（bottom-up），並加做 LLM 純歸納
  輪與黃金標準的映射分析。映射分析方法須在看到結果前寫入
  `methodology.md`。
- **完整歌詞不進 git**（版權）；API 金鑰走 `.env`。
- **專案目錄維持原名 `pop-fem-audit`**：API 管線下目錄名不會
  進入模型輸入，無污染疑慮。

## 2026-07-31

- **專案英文名定為「A Feminist Audit of Pop Music」**：明示
  女性主義立場，「audit」兼指對歌曲與對 LLM 標籤系統的稽核，
  並與縮寫 `pop-fem-audit` 對應。
- **程式碼收整為 `tools/` src-layout 子專案**：發行名
  `pop-fem-audit-tools`、import 套件名 `pop_fem_audit_tools`、
  description「Tools for A Feminist Audit of Pop Music.」；
  以 `pip install -e tools/` 安裝、`python -m
  pop_fem_audit_tools.run_llm` 執行；相依套件記於
  `pyproject.toml`（`requirements.txt` 移除）；Sphinx 文件
  暫緩。理由：後續多支程式將共用程式碼，套件化後測試可用
  正常 import；目錄名 `tools/` 經無脈絡的獨立 subagent 命名
  評估選出，最誠實反映「服務研究的輔助工具」定位——研究
  本體在根目錄的 prompts/、runs/、results/，程式只是配套。
- **CLI 入口改為套件層級 dispatcher**：dispatcher 為單一
  入口，`run_llm.py` 的 entry point 移除；有兩種等價呼叫
  形式——`python -m pop_fem_audit_tools run-llm ...` 與
  console script `pop-fem-audit-tools run-llm ...`
  （`[project.scripts]`）。理由：後續多支工具共用單一入口，
  `--help` 可列出全部子命令，重現文件穩定。
- **資料儲存架構定案**：commit 判準——凡能由「committed 輸入＋
  committed 程式」決定性再生者不 commit；源頭、外部捕捉、人工
  著作以文字格式 commit。工作儲存採 SQLite 單檔
  （`tools/instance/`，generated、不進 git；歌詞全文入 DB 故無
  版權疑慮），schema 以 SQLAlchemy 2.0 typed ORM 定義，設定經
  pydantic-settings（`.env`）。`results/` 報表 CSV 為「可再生仍
  commit」的唯一例外，理由：論文引用穩定性、審稿人零門檻、
  撰稿期數字變動可 diff。（本條經多輪辯證後定案，推翻 Claude
  最初的全 CSV 方案。）
- **資料模型**：songs、chart_entries（1—N）、artists、
  song_artists（M—N：角色、署名順序）、lyrics（1—1）；領域
  不變量檢查內建 `build-db`，違規即失敗。
- **歌手背景擴充與防火牆**：歌手資料擴為實體表（QID、性別、
  型態、曲風、國籍），women-power 候選的歌手另做深度背景
  （族裔以公開自我認同為準、音樂場景），供人工解讀與論文
  討論；**歌手背景絕不進 LLM 輸入**（歌詞-only），避免光環
  偏誤污染條件 A/B 實驗。
- **沿用先導研究歌詞捕捉**（lyrics.json，684 首，2018–2025）：
  只匯入識別欄位與歌詞本文，pilot 分析欄位不匯入；以
  (year, rank) 精確匹配。出處記於 `lyrics_provenance.csv`：
  source（原始 API）與 method（pilot-import / api-fetch）
  兩層；取得日期不可考者不假造，僅記可證上界。
- **`run_llm` 改走 pydantic-settings 統一設定**（刪手寫 .env
  parser），與 `config.py` / `database.py` 一致。
- **`lyrics` 表併入 `songs.lyrics` nullable 欄位**（資料模型由
  五表改四表）。理由：1—1 關係在此量級下獨立成表只有正規化
  慣性，nullable 欄位更簡單；「未取得」以 NULL 表達，語意
  等價。

## 2026-08-01

- **引擎獨立性以 PostgreSQL/SQLite 為範圍**（MySQL 的 VARCHAR
  長度限制不處理）。
- **`build-db` 的重置改用逐表 DELETE，不再 drop/create**：
  schema 生命週期歸 migration 管，build-db 只管資料。連帶
  效果：重置成為純 DML,全程單一交易、驗證通過才 commit——
  建置失敗時前一版資料完好。首次執行仍以 create_all
  （checkfirst）補缺表。
- **song/artist ID 由 build-db 顯式指派**（首次出現順序 1、2、
  3…），不依賴 autoincrement——PostgreSQL 的 sequence 在
  DELETE 後不重置，顯式指派讓重建決定性跨引擎成立。
- **禁止文字 SQL statement，一律經 SQLAlchemy ORM/Core API**。
  唯一記錄在案的例外：SQLite 的 `PRAGMA foreign_keys=ON`
  （官方建議作法，無非文字 API 可用；SQLite 的 FK 旗標為
  逐連線設定）。裁定其歸屬為連線組態，實作於 `database.py`
  的 `__create_engine`——建 engine 時對 SQLite 註冊 connect
  listener，所有消費者全程生效，不再由 build-db 各自註冊。

## 2026-08-02

- **`import-lyrics` 不設為子命令，pilot 歌詞改以私人腳本
  匯入**。理由：pilot 捕捉檔不隨論文發布，子命令
  形式會在發布的 CLI 裡留下讀者無法執行的死命令——要交待的
  是「沿用 pilot 捕捉」的事實（記於 lyrics_provenance.csv 與
  論文方法節），不是工具本身；工具移出專案，發布管線即
  「讀者可完整執行的程序」。讀者重現歌詞的路徑為
  `fetch-lyrics`，API 漂移造成的差異屬捕捉層的已承認限制。
  provenance 的 method 值域定為
  pilot-import / api-fetch / manual。
- **資料路徑全面改為顯式 CLI 引數**——必要運算元為位置
  引數、選擇性輸入為選項（build-db 吃榜單 CSV 一個位置引數，
  歌詞目錄、Wikidata 快照、overrides 為 `--lyrics-dir`／
  `--wikidata-csv`／`--overrides-csv` 三個選項；fetch-lyrics
  吃歌詞目錄、provenance、缺漏報表三個位置引數；fetch-artists
  吃快照檔；run-llm 吃 runs 目錄），命令與 CWD 無關，且每次
  執行觸碰的檔案完整見於指令本身。省略選項即不載入該捕捉層；
  給了選項而路徑不存在即建置失敗，取代原本的默默跳過。理由：
  settings 的 `.env` 依 pydantic 慣例讀自 CWD（約定
  `tools/`），資料路徑原以 repo 根為 CWD，兩者衝突；顯式引數
  消滅隱性 CWD 契約，亦拒絕以父目錄推導兄弟檔案的隱性慣例。
- **`data/` 依生命週期分三層**：`source/`（源頭，手放後不動）、
  `captures/`（外部捕捉，只由 fetch 命令與私人匯入腳本寫入）、
  `manual/`（人工著作，只由研究者手寫；之後的黃金標準編碼
  亦居此）。理由：三種生命週期混住一層，目錄無法傳達「誰可以
  寫哪裡」；顯式引數化後搬遷零程式改動。
