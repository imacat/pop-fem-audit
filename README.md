# pop-fem-audit

流行音樂中「女性力量」語彙的挪用與污染——以 Billboard Year-End
Hot 100（2016–2025）為例的內容分析。

台灣女性學學會 2026 年會論文之研究資料與分析程式。

## 目錄結構

見 `docs/project-structure.md`。研究步驟規劃見
`docs/research-plan.md`；方法細節見 `docs/methodology.md`；
人工編碼手冊見 `docs/codebook.md`；決策日誌見
`docs/decision-log.md`。

## 重現方式

1. 準備 Python 3.14+ 環境，安裝分析管線套件：
   `pip install -e tools/`。
2. 自 `tools/.env.example` 建立 `tools/.env`，寫入
   Anthropic API 金鑰。
3. 依 `docs/research-plan.md` 的階段順序，於 `tools/` 目錄下
   執行子命令，必要輸入以位置引數、選擇性輸入以選項給定（如
   `pop-fem-audit-tools build-db
   ../data/source/yearend_hot100_2016_2025.csv
   ../data/derived
   --lyrics-dir ../data/captures/lyrics
   --wikidata-csv ../data/captures/artists-wikidata.csv`）。
   LLM 步驟使用 `claude-sonnet-4-6`、temperature=0、
   thinking 關閉；輸出可逐項比對的步驟獨立執行三次，由
   程式取三票多數決定案（「三次執行＋多數決」協定），
   自由生成步驟兩次執行進池。
4. 每次執行的完整紀錄（定義檔快照、原始輸出、參數）存於
   `runs/`，可逐筆稽核。論文引用的最終資料表在 `results/`。

注意：歌詞受版權保護，`data/captures/lyrics/` 不隨 repo 發布，須自行
以 `tools/` 中的抓取程式重建。

## 授權

（待定）
