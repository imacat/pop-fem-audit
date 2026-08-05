# 執行成本記錄

每次 `run-llm` 執行的 token 用量與費用。用量取自各歸檔的
`meta.json`；費用以 `claude-sonnet-4-6` 牌價（input $3／
百萬 token、output $15／百萬 token）經 Batch API 半價
計算：

    費用 = (input × 3 + output × 15) / 1,000,000 / 2

被 `--replace` 取代的執行以「已取代」標記，數字保留供
總支出核算。

| 日期 | 步驟 | 執行 | 批次 ID | 耗時 | input | output | 費用 (USD) | 狀態 |
|---|---|---|---|---|---:|---:|---:|---|
| 2026-08-04 | 01-01-01-tag | run1 | msgbatch_01PTACDQMr8M6ahnshbedjtB | 6 分 27 秒 | 763,318 | 338,661 | $3.68 | 已取代（浮水印清洗與防圍欄修訂後重跑） |
| 2026-08-05 | 01-01-01-tag | run1 | msgbatch_01TikJNd2pZVxzQ8SaybVthu | 4 分 57 秒 | 774,604 | 323,651 | $3.59 | 已取代（合法 JSON 修訂後重跑） |
| 2026-08-05 | 01-01-01-tag | run1 | msgbatch_01JFBCNqnu1cwXyqmEKLHQYF | 4 分 30 秒 | 790,370 | 328,227 | $3.65 | 已取代（song-288 平台失敗，整批重跑驗證） |
| 2026-08-05 | 01-01-01-tag | run1 | msgbatch_01VSDneWuSbf8mShA32jiWrX | 6 分 15 秒 | 790,370 | 326,193 | $3.63 | 已取代（措辭修訂後全體重跑） |
| 2026-08-05 | 01-01-01-tag | run1-rescue-288 | msgbatch_019Hq6bNVXVmp4DjRZ2cgVda | 2 分 5 秒 | 1,015 | 376 | $0.01 | 已取代（措辭修訂後全體重跑，該首原生通過）|
| 2026-08-05 | 01-01-01-tag | run1 | msgbatch_01VgZ77KAPGWmuu3PnQFqZ7Q | 7 分 1 秒 | 794,913 | 326,435 | $3.64 | 現行 |

累計支出：$18.20。
