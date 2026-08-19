# 常設工作規範

本專案的常設工作規範。原專案 `CLAUDE.md`；移置於此，
使 Claude Code subagent 不將其繼承入 context（盲判型
agent 不得見之）。凡於本專案工作的主會話，動手管線、
資料或文件之前，先讀本檔。

## 分析管線

管線已跑畢；本規範適用於任何重跑或擴充。

- LLM 分析以 Python 腳本呼叫 Anthropic Messages API
  執行，能用 Batch API 處即用之。步驟 1 與步驟 3 以
  `claude-sonnet-4-6` 執行，`temperature=0`、thinking
  停用；步驟 4 與步驟 5 以 `claude-fable-5` 執行，該
  模型兩個參數皆不受理——步驟 4 的取樣變異由多數決
  吸收，步驟 5 由整合三份閱讀吸收。
- 定義檔置於 `prompts/<步><次步>-<task>.md`（如
  1-tag.md、5a-read.md；次步以字母標示，與論文正文的
  步驟編號一致；不帶版本號——版本即 git 歷史），逐字
  作為 system prompt。
- 逐項的 LLM 判斷（步驟 3 的逐首編碼、步驟 4 的逐碼
  入群判斷）以同一份定義檔、同一份輸入獨立執行三次；
  再由確定性計票將三次執行中至少兩次指派的項目（一個
  （歌，關鍵字）或（群，關鍵字）配對）收入定案
  （「三次執行＋多數決」）。自由生成步驟執行兩次，
  兩份輸出進池。步驟 5 的質性閱讀兩者皆非：逐首三次
  獨立閱讀，由各自的定義檔逐首整合、跨首統整——質性
  協定，不是投票（見 docs/methodology.md）。詞彙表由
  確定性子命令建構（嵌入＋分群），不經 LLM。驗證結果
  不符預期時，修訂定義檔並重複該循環；絕不手改結果。
- 一步的每次執行皆自我完備歸檔於 `run-llm` 命令列上
  明示指定的目的目錄下（慣例為
  `runs/<步驟>/run<N>/`）：定義檔快照、原始輸出與
  `meta.json`（model ID、參數、時間戳、batch ID）。
  一步的 N 次執行即 N 次各自的 `run-llm` 呼叫。覆蓋
  既有執行歸檔須明示旗標；被取代的執行留在 git 歷史。
  確定性步驟歸檔於 `runs/<步驟>/`，不分 `run<N>` 層。
- 每次 `run-llm` 執行的 token 用量與費用記入
  `docs/run-costs.md`，與執行歸檔同一 commit。
- 腳本自環境變數 `ANTHROPIC_API_KEY` 讀取 API key
  （`.env`，gitignored）。

## 資料規則

- `data/source/` 存手放後不動的原始檔；
  `data/captures/` 只由 fetch 命令與私人匯入腳本
  寫入；`data/manual/` 只由研究者親手寫入；
  `data/derived/` 只由 `build-db` 子命令寫入。
- 歌詞全文有版權：一律置於 `data/captures/lyrics/`
  （gitignored），絕不 commit，亦絕不於 repo 任何處
  全文重現。

## 文件

- `results/` 存計票後的定案表（論文所引）；`runs/` 存
  原始稽核紀錄。論文只引 `results/`。
- **Commit 判準**：凡能由「committed 的輸入＋committed
  的程式」決定性再生者不 commit；凡不能者一律以文字
  格式 commit，格式跟著上文「資料規則」一節所定的
  層次走。例外：`results/` 定案表與
  `data/derived/` 人讀報表雖可再生仍 commit——理由是
  引用穩定性、審稿人零門檻、撰稿期數字變動可 diff；
  兩者皆與工作儲存同一動作產出，稽核鏈無中間空缺。
- 凡定義檔或研究規劃之更動，皆記入
  `docs/decision-log.md`，註明日期與原因。
