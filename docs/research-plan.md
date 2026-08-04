# 研究步驟規劃

（2026-07-30 討論定案、2026-07-31 增補資料架構；
後續變更請記入 `decision-log.md`）

## 總體框架

- **研究敘事**：全文為獨立完整的正式研究（2016–2025 十年語料
  共 1000 筆榜單紀錄，凍結程序後全量執行），**不與先導研究
  做比較**；全文數字一律以正式研究
  結果為準。先導研究僅作為 codebook v0 與假說的內部來源，
  記於決策日誌，不進入論文敘事。
- **執行原則**：主會話只做討論；所有分析由 deterministic script
  執行。LLM 步驟以 Python script 呼叫 Anthropic Messages API
  （個人 Console 帳號、Batch API 五折），定義檔逐字作為 system
  prompt。每個 LLM 步驟「同一定義檔獨立執行兩次 + 一次仲裁」
  （2+1），仲裁結果不符預期則修訂定義檔重跑整個循環。
- **模型**：`claude-sonnet-4-6`、temperature=0、thinking 關閉
  （此組合非決定性最低、成本合理）。條件 A/B 盲點實驗為
  自足設計：同語料、同模型、僅提示不同，對照黃金標準。
  其他工具性環節於階段 3 以校準樣本實測 Sonnet 4.6 vs Opus 5
  的一致率後決定是否升級。
- **信度與效度分工**：2+1 協定量測穩定性（intra-rater
  reliability，報告一致率／kappa）；效度靠理論 codebook 與
  人工黃金標準終審。可重現性定義為「程序透明＋可稽核」：
  公開定義檔、記錄 model ID 與執行時間、保存全部原始輸出。

## 資料儲存與模型（2026-07-31 定案）

- **Commit 判準**：凡能由「committed 的輸入＋committed 的程式」
  決定性再生者，不 commit；凡不能者——源頭資料、外部世界的
  捕捉（Wikidata 快照、LLM 原始輸出）、人工著作（核定、編碼）
  ——一律以文字格式 commit。格式跟著層次走，不跟著偏好走。
- **分層**：
  - 源頭：原始榜單 CSV（進 git）。
  - 捕捉：Wikidata 快照 CSV、你的編碼
    CSV、`runs/` JSONL（皆進 git）；歌詞 `.txt` 快取
    （版權因素 gitignored，為已知的稽核缺口）。
  - 工作儲存：SQLite 單檔（`tools/instance/`，generated、
    不進 git），SQLAlchemy 2.0 typed ORM 定義 schema，
    設定經 pydantic-settings（`.env` 供應
    `SQLALCHEMY_DATABASE_URL` 與 `ANTHROPIC_API_KEY`）。
    歌詞全文入 DB（不進 git 故無版權疑慮）。
  - 衍生：`build-db` 建置工作儲存的同一動作產出人讀報表
    （`data/derived/` 的 songs.csv、artists.csv，進 git）——
    與 SQLite 同交易語意，稽核鏈無中間空缺；不含資料庫 ID。
  - 報表：論文引用的最終表由 export 產出 CSV 進 `results/`。
    衍生與報表為「可再生仍 commit」的兩個例外，理由：引用
    穩定性（十年尺度的環境會腐化）、審稿人零門檻、撰稿期
    數字變動可 diff、供人工檢視。
- **資料模型**：`songs`（歌曲實體，含 lyrics nullable 欄位）、
  `chart_entries`（1 歌—N 筆榜單紀錄）、`artists`（歌手實體：
  Wikidata QID、性別、型態、曲風、國籍）、`song_artists`
  （M—N 關聯：角色、署名順序）。領域不變量（恰 1000 筆榜單、
  每歌至少一 primary 歌手等）檢查內建於 `build-db`，違規即
  建置失敗。
- **歌手背景防火牆**：歌手背景資料只進人工解讀階段（證據表、
  論文討論），**絕不進 LLM 輸入**——LLM 分類的 user message
  維持歌詞-only，避免光環偏誤污染條件 A/B 實驗。women-power
  候選歌曲的歌手另做深度背景（族裔以公開自我認同為準、音樂
  場景），script 輔助、人工核定。
- **Pilot 歌詞沿用（私人匯入，不進發布管線）**：先導研究
  捕捉檔（lyrics.json，684 首，2018–2025）以私人腳本
  匯入歌詞快取——只取識別欄位與歌詞本文，以
  (year, rank) 精確匹配 song_id。匯入工具不屬於專案交付物
  （讀者拿不到其輸入），讀者的重現路徑純粹是 `fetch-lyrics`；
  沿用之**事實**記於 `data/captures/lyrics-provenance.csv`（進 git）：
  `source`（原始 API）與 `method`
  （pilot-import / api-fetch / manual）兩層，取得日期不可考者
  不假造，僅記可證上界。
- **子命令**（`pop-fem-audit-tools <cmd>` 或
  `python -m pop_fem_audit_tools <cmd>`）：`run-llm`、
  `build-db`、`fetch-lyrics`、`fetch-artists`（皆已完成）、
  `export-llm-input`（階段 2 前補上）；之後再加報表 export
  與統計。

## 階段與時程（全文截稿 2026-08-15）

| 階段 | 內容 | 方式 | 時程 |
|---|---|---|---|
| 0 | 基礎建設：git init、目錄結構、.gitignore、決策日誌、runner script（含 Batch API）、codebook v0 骨架 | script + 討論 | 7/30–7/31 |
| 1 | 資料準備：`run_llm` 改走統一設定 → `build-db`（解析榜單成 songs/chart_entries/artists/song_artists）→ `import-lyrics`（pilot 2018–2025）→ `fetch-lyrics`（2016–17 與缺漏，Lyrics.ovh / LRCLIB）→ `fetch-artists`（Wikidata 快照）→ `export-llm-input` | 子命令 | 7/31–8/3 |
| 2 | 候選篩選：全部唯一歌曲高召回 women-power 候選篩選（寧可多抓，人工剔除） | API 2+1 | 8/2–8/3 |
| 3 | 黃金標準：依 codebook 人工逐首判定 genuine/peripheral/fake，附引用歌詞證據表（LLM 只做摘錄，不給判定建議）；先以 10–15 首校準樣本試編並修訂 codebook 後凍結；同批校準樣本實測 Sonnet 4.6 vs Opus 5 一致率 | 人工 + script 輔助 | 8/4–8/8 |
| 4 | 受控比較（盲點實驗）：條件 A（詞彙層提示）vs 條件 B（框架感知提示），各 2+1，對照黃金標準計算假陽／假陰率 | API | 8/6–8/9 |
| 4' | 由下而上歸納輪：LLM 對候選歌曲做無理論主題編碼（定義檔不含女性主義詞彙），與黃金標準做映射分析（交叉表；分析方法先寫入 methodology.md 再看結果） | API 2+1 + script | 與 4 並行 |
| 5 | pussy 修辭分析：script 找含詞歌曲 → LLM 分類（METONYM/ANATOMICAL/COWARD/OTHER + 說話者/指涉對象）2+1 → 人工核定 | script + API | 8/8–8/10 |
| 6 | 統計與圖表：一致率（kappa）、污染率、類型分布、年度趨勢、映射交叉表 | scripts | 8/10–8/11 |
| 7 | 撰寫全文＋內部審稿（subagent 以審稿人視角挑毛病，特別是嘻哈女性主義／respectability politics 一題） | 討論 + subagent | 8/10–8/14 |

關鍵路徑：階段 3 人工編碼（僅研究者本人可做），排週末與晚間分批。

## Codebook 原則

- Directed content analysis：理論骨架（top-down）＋紀律化歸納通道
  （bottom-up：`other-fake` 開放碼 + memo + 決策日誌）。
- 三層結構：理論構念層（Banet-Weiser、Gill、Goldman、McRobbie、
  Fredrickson & Roberts、Connell、Mulvey）→ 操作判準層（權力來源
  測試、frame vs vocabulary、決策樹）→ 類別定義層（A–E 納入／
  排除判準、例句、near-miss 反例）。
- 判準層須明文回應嘻哈女性主義（Joan Morgan、Gwendolyn Pough）
  與性積極女性主義的 respectability politics 質疑：區分「性表達」
  與「貶低其他女性／以男性指標定義權力」。
- 流程：v0 → 校準樣本試編 → 修訂 → 凍結 v1 → 全量編碼；
  中途修訂須記決策日誌並回檢已編歌曲。

## 其他已定案事項

- 歌詞受版權保護：完整歌詞不進 git（`data/captures/lyrics/` gitignored），
  論文與 repo 只留分類所引摘錄。
- Fable 5 不用於 pipeline：成本高、thinking 無法關閉且不可稽核、
  無 temperature 控制，且會混淆「盲點是提示問題」的核心主張。
