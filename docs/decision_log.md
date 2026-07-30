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
