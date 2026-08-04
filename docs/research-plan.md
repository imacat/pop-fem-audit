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
  prompt。2+1 協定依輸出可比性適用：輸出可逐項機械比對的步驟
  （收斂、編碼）「同一定義檔獨立執行兩次＋一次仲裁」，仲裁
  只裁程式算出的分歧清單；自由生成步驟（首步自由標註）兩次
  執行全數進池、不仲裁——自由詞彙兩次輸出不共享比對單位，
  無物可裁。仲裁結果不符預期則修訂定義檔重跑該循環。
- **提示詞只定格式、不定語意**：研究對象是通用 LLM 以其
  網路語料知識背景所做的自然編碼，編碼結果本身是批判對象。
  LLM 定義檔只規定任務形狀（輸入、數量範圍、輸出格式），
  不給任何主題的定義、判準或範例；研究者的深度判準只寫在
  codebook（人工黃金標準用），兩者不互相滲透。LLM 編碼
  一律要求逐標籤引述歌詞原句，作為檢視編碼偏差的依據。
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
  維持歌詞-only，避免光環偏誤污染條件 A/B 實驗。「女性力量」
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

## 自然編碼管線（2026-08-04 定案）

主題編碼採四步驟管線，歌詞只出現在第 1、4 步；第 2、3 步
是純概念整理（目標是產生 codebook 詞彙表，不是編碼）。

1. **自由標註（tag）**：逐首歌請模型標註 thematic
   keywords，附歌詞引述；提示零語意內容。獨立執行兩次，
   兩次輸出全數進池（記錄執行別），不仲裁。粒度鎖定
   thematic keywords：前導研究三粒度比較（keywords 過碎、
   themes 過早抽象）之繼承，於執行前鎖定，防止事後擇優。
2. **自然收斂（merge）**：輸入為池中純去重關鍵字清單——
   無歌詞、無頻次、無歌曲出處——模型按自身理解合併近似
   概念。2+1：兩次收斂處理同一批輸入詞，程式算出共識塊
   與分歧塊對，逐對仲裁（仲裁自身亦 2+1，第三票終局）後
   以連通元件決定性重組；收斂執行不命名，組名由命名步驟
   2+1 定案（演算法詳見 `methodology.md`）。
3. **強制收斂（cap）**：同第 2 步形態，輸入為 merge
   定案後的組名清單（原始關鍵字不下傳），限制併至 50 個
   以內；仲裁後略超 50 可接受，如實記錄。頻次不入收斂：頻率的分析角色由第 4 步編碼承擔；
   池中頻次含跨執行噪音；頻次會誘使模型以頻率剪枝（喪失
   稀有主題）並把高頻大主題切細。代價（特異主題佔名額）
   已知並接受，換取主題多樣性與純語意歸併的可辯護性。
4. **編碼（code）**：以定稿詞彙表對全部歌曲 2+1 編碼——
   模型讀歌詞、逐標籤附引述；逐首計一致率，分歧逐首仲裁
   （仲裁者看歌詞與兩邊引述）。此為主儀器，「女性力量」
   候選集由此浮現；亦是對前導研究「映回後未對照歌詞」
   限制的明文改良。沿收斂軌跡的機械對映（純程式）保留為
   零成本診斷副產品，量測收斂軌跡的扭曲，不作主結果。

另設**「女性力量」單目標篩選（screen）**：單目標提示、
附引述、全量執行，僅作為黃金標準取樣的補漏網——把「模型
被明示提醒後認得出」的歌撈進人工審視範圍，以量測模型漏標
方向的偏差；不進偏差統計的分子分母定義。逐首 2+1（有／無
＋引述，逐首仲裁）；同樣不給定義，提示僅含標籤詞與任務
形狀。標籤詞用 `women-power`——研究者任意決定的先驗
主題，即本研究的論文主題本身，不由資料產生。其結果僅作
召回之用，永不進任何統計的分子分母。標籤詞是 screen
提示中唯一的語意種子，屬研究者的儀器選擇，據實揭露。

定義檔命名 `prompts/<軌>-<步>-<次步>-<task>.md`——軌
01＝由下而上自然編碼、02＝預先決定的 women-power
篩選；步為軌內步驟序，次步為
步內執行順序，讀者依編號先後依循（如 01-02-01-merge.md →
01-02-02-merge-arb.md → 01-02-03-merge-arb-arb.md →
01-02-04-merge-name.md → 01-02-05-merge-name-arb.md）。
後綴 `-arb` 為仲裁、`-arb-arb` 為仲裁之終局票、`-name`
為命名、`-name-arb` 為命名擇一仲裁。檔名不帶
版本號——版本即 git 歷史，失敗的版本不保留，需要回看的
舊版都在 git history；每次執行的定義檔快照隨 `runs/`
自我完備。收斂執行的輸出本身即分組記錄（無名分組
JSON），與全部中間交接檔同隨 `runs/` 歸檔（交接契約見
`methodology.md`）。

## 階段與時程（全文截稿 2026-08-15）

| 階段 | 內容 | 方式 | 時程 |
|---|---|---|---|
| 0 | 基礎建設：git init、目錄結構、.gitignore、決策日誌、runner script（含 Batch API）、codebook v0 骨架 | script + 討論 | 7/30–7/31 |
| 1 | 資料準備：`run_llm` 改走統一設定 → `build-db`（解析榜單成 songs/chart_entries/artists/song_artists）→ `import-lyrics`（pilot 2018–2025）→ `fetch-lyrics`（2016–17 與缺漏，Lyrics.ovh / LRCLIB）→ `fetch-artists`（Wikidata 快照）→ `export-llm-input` | 子命令 | 7/31–8/3 |
| 2 | 自然編碼管線：tag ×2 進池 → merge 2+1 → cap 2+1 → 詞彙表定稿 → code 2+1（全 883 首，附引述）；另跑 screen 補漏網 | API + script | 8/4–8/7 |
| 3 | 黃金標準：依 codebook 人工逐首判定 genuine/peripheral/fake，附引用歌詞證據表（LLM 只做摘錄，不給判定建議）；先以 10–15 首校準樣本試編並修訂 codebook 後凍結；同批校準樣本實測 Sonnet 4.6 vs Opus 5 一致率 | 人工 + script 輔助 | 8/5–8/9 |
| 4 | 受控比較（盲點實驗）：條件 A（詞彙層提示）vs 條件 B（框架感知提示），各 2+1，對照黃金標準計算假陽／假陰率 | API | 8/8–8/11 |
| 4' | 映射分析：自然編碼結果（第 4 步）與黃金標準交叉表；軌跡對映 vs 直接編碼的扭曲診斷（分析方法先寫入 methodology.md 再看結果） | script | 與 4 並行 |
| 5 | pussy 修辭分析：script 找含詞歌曲 → LLM 分類（METONYM/ANATOMICAL/COWARD/OTHER + 說話者/指涉對象）2+1 → 人工核定 | script + API | 8/9–8/11 |
| 6 | 統計與圖表：一致率（kappa）、污染率、類型分布、年度趨勢、映射交叉表 | scripts | 8/11–8/12 |
| 7 | 撰寫全文＋內部審稿（subagent 以審稿人視角挑毛病，特別是嘻哈女性主義／respectability politics 一題） | 討論 + subagent | 8/11–8/14 |

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
