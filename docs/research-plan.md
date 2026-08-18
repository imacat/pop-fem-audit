# 研究步驟規劃

（2026-07-30 討論定案；2026-08-15 依執行現況全面改寫，
舊版規劃見 git 歷史；歷次變更與理由記於 `decision-log.md`，
程序細節見 `methodology.md`）

## 總體框架

- **研究敘事**：全文為獨立完整的正式研究（2016–2025 十年
  語料共 1000 筆榜單紀錄、883 首歌，凍結程序後全量執行），
  **不與先導研究做比較**；
  全文數字一律以正式研究結果為準。先導研究僅作為假說的
  內部來源，記於決策日誌，不進入論文敘事。
- **執行原則**：主會話只做討論；所有分析由 deterministic
  script 執行。LLM 步驟以 Python script 呼叫 Anthropic
  Messages API（個人 Console 帳號、Batch API 五折），定義
  檔逐字作為 system prompt。可逐項機械比對的判斷（步驟 3
  編碼、步驟 4 選群、步驟 5d 樣態標註）採「同一定義檔
  獨立執行三次＋多數決」，計票由確定性子命令完成。自由
  生成（步驟 1 自由標註）兩次執行全數進池。步驟 5a 至
  5c 為質性閱讀協定：三次獨立閱讀為分析者三角檢核、
  逐首整合、樣態統整產出草稿，不適用投票與仲裁。詞彙表
  不經 LLM，由詞向量嵌入＋確定性分群產生。驗證結果不符
  預期則修訂定義檔重跑該循環，絕不手改結果。
- **提示詞只定格式、不定語意**：研究對象是通用 LLM 以其
  網路語料知識背景所做的自然編碼與閱讀，其結果本身是
  批判對象。定義檔只規定任務形狀（輸入、數量範圍、輸出
  格式），不給任何主題的定義、判準或範例。LLM 判斷一律
  要求逐項引述歌詞原句，作為檢視偏差的依據。
- **模型**：步驟 1、3 用 `claude-sonnet-4-6`（temperature=0、
  thinking 關閉）；步驟 4、5 用 `claude-fable-5`（兩參數
  不適用，均不送出；取樣變異由多數決或整合吸收）——實測
  發現 sonnet 將「Women Power」拆讀為 women＋power 的組合
  語意，fable-5 讀為詞彙化概念，語意層任務因此換用
  fable-5（經過見決策日誌）。
- **信度與效度**：三次獨立執行量測穩定性（intra-rater
  reliability，可報告兩兩一致率）；封閉母體全量檢查取代
  抽樣防衛。可重現性定義為「程序透明＋可稽核」：公開定義
  檔、記錄 model ID 與執行時間、保存全部原始輸出。

## 資料儲存與模型

- **Commit 判準**：凡能由「committed 的輸入＋committed 的
  程式」決定性再生者，不 commit；凡不能者——源頭資料、
  外部世界的捕捉（Wikidata 快照、LLM 原始輸出）、人工
  著作——一律以文字格式 commit。格式跟著層次走。
- **分層**：
  - 源頭：原始榜單 CSV（進 git）。
  - 捕捉：Wikidata 快照 CSV、`runs/` JSONL（皆進 git）；
    歌詞 `.txt` 快取（版權因素 gitignored，為已知的稽核
    缺口）。
  - 人工：`data/manual/`（僅研究者親手寫入：編碼修正、
    演唱者性別修正）。
  - 工作儲存：SQLite 單檔（`tools/instance/`，generated、
    不進 git），SQLAlchemy 2.0 typed ORM 定義 schema，
    設定經 pydantic-settings（`.env` 供應
    `SQLALCHEMY_DATABASE_URL` 與 `ANTHROPIC_API_KEY`）。
    歌詞全文入 DB（不進 git 故無版權疑慮）。
  - 衍生：`build-db` 建置工作儲存的同一動作產出人讀報表
    （`data/derived/`，進 git），與 SQLite 同交易語意。
  - 報表：論文引用的定案表進 `results/`——
    `codings.csv`（步驟 3 定案編碼）、`groups.csv`
    （步驟 4 定案編碼群）、`patterns.csv`（步驟 5c 定案
    樣態表）、`annotations.csv`（步驟 5d 定案歌×樣態
    矩陣）。衍生與報表為「可再生仍 commit」的例外，理由：
    引用穩定性、審稿人零門檻、撰稿期數字變動可 diff。
- **資料模型**：`songs`（含 lyrics、`performer_gender`——
  演唱聲音之性別，由署名藝人之 Wikidata 性別推導後套用
  `data/manual/performer-gender-corrections.csv` 手工修正）、
  `chart_entries`、`artists`、`song_artists`、`codings`、
  `groups`（語意編碼群）、`patterns`（深讀樣態）、
  `annotations`（歌×樣態定案矩陣）。領域不變量（恰 1000
  筆榜單、每歌至少一 primary 歌手等）檢查內建於
  `build-db`，違規即建置失敗。
- **歌手背景防火牆**：歌手背景資料只進人工解讀階段，
  **絕不進 LLM 輸入**——LLM 任務的 user message 維持
  歌詞-only 或管線中間產物-only，避免光環偏誤。
- **Pilot 歌詞沿用（私人匯入，不進發布管線）**：先導研究
  捕捉檔（lyrics.json，684 首，2018–2025）以私人腳本
  匯入歌詞快取；讀者的重現路徑純粹是
  `fetch-lyrics`；沿用之事實記於
  `data/captures/lyrics-provenance.csv`（進 git）。
- **子命令**（`pop-fem-audit-tools <cmd>`）：`build-db`
  （`--codings`、`--groups`、`--gender-corrections`、
  `--patterns`、`--annotations`）、`cluster-keywords`、
  `export-llm-input`、`fetch-artists`、`fetch-lyrics`、
  `run-llm`（`--model` 於模型登錄表中擇一）、
  `tally-codings`、`tally-groups`、`tally-annotations`。

## 分析管線（五步驟，全部完成）

1. **自由標註（步驟 1）**：逐首歌請模型標註 thematic
   keywords，附歌詞引述；提示零語意內容。獨立執行兩次，
   兩次輸出全數進池。
2. **詞彙表建構（步驟 2）**：聯集去重後以句向量模型嵌入、
   階層式聚合分群 k=100，組名取 medoid；再併入研究者先驗
   主題詞 `women-power`（據實揭露的儀器介入），共 101 碼。
3. **編碼（步驟 3）**：以定稿詞彙表對全 883 首編碼，逐
   標籤附引述，×3＋多數決（`tally-codings`），定案
   `results/codings.csv`。「女性力量」候選集（wp 66 首、
   fe 144 首、wp∪fe 145 首）由此浮現。
4. **語意編碼群（步驟 4）**：LLM 依編碼字面語意將 101 碼
   選入研究者指定的四個主題群（women-power／misogyny／
   masculine／vulnerable），×3＋多數決（`tally-groups`），
   定案 `results/groups.csv`；wp/fe 與各編碼、各編碼群之
   關聯統計（BH-FDR 校正）入論文。
5. **女性主義問題之質性深讀（步驟 5）**：對 wp∪fe 145 首
   ——5a 逐首盲讀（僅歌詞全文）×3；5b 逐首整合（收斂
   註記、主清單限兩讀以上）；5c 樣態統整（全體基底＋
   男聲／女聲／混合三個發話脈絡分組）；5d 樣態標註——
   以分組樣態表逐首標註「有問題」的 111 首，×3＋多數決
   （`tally-annotations`），定案 `results/patterns.csv` 與
   `results/annotations.csv`。

定義檔命名 `prompts/<步><次步>-<task>.md`，次步以字母標示
（與論文正文的步驟編號一致）；編號的所指是工序而非定義檔
（確定性的第 2 步無定義檔仍佔編號）；檔名
不帶版本號——版本即 git 歷史；每次執行的定義檔快照隨
`runs/` 自我完備，token 費用逐筆記於 `docs/run-costs.md`。

## 時程與剩餘工作

- 全文截稿 2026-08-15；已向主辦致歉延後一至二日交件。
- 分析管線與定案表全部完成；剩餘為論文撰寫：「挪用與
  污染」結論（步驟 5 素材已備）、信度說明、fe 與新自由
  主義敘事之詮釋標註。

## 其他已定案事項

- 歌詞受版權保護：完整歌詞不進 git
  （`data/captures/lyrics/` gitignored），論文與 repo 只留
  分析所引摘錄。
