# 執行成本記錄

每次 `run-llm` 執行的 token 用量與費用。用量取自各歸檔的
`meta.json`；費用以各模型牌價（每百萬 token：sonnet-4-6
$3／$15、opus-4-6 $5／$25、opus-5 與 fable-5 $10／$50）
經 Batch API 半價計算：

    費用 = (input × in價 + output × out價) / 1,000,000 / 2

被 `--replace` 取代的執行以「已取代」標記，數字保留供
總支出核算。

| 日期 | 步驟 | 執行 | 模型 | 批次 ID | 耗時 | input | output | 費用 (USD) | 狀態 |
|---|---|---|---|---|---|---:|---:|---:|---|
| 2026-08-04 | 01-01-01-tag | run1 | claude-sonnet-4-6 | msgbatch_01PTACDQMr8M6ahnshbedjtB | 6 分 27 秒 | 763,318 | 338,661 | $3.68 | 已取代（浮水印清洗與防圍欄修訂後重跑） |
| 2026-08-05 | 01-01-01-tag | run1 | claude-sonnet-4-6 | msgbatch_01TikJNd2pZVxzQ8SaybVthu | 4 分 57 秒 | 774,604 | 323,651 | $3.59 | 已取代（合法 JSON 修訂後重跑） |
| 2026-08-05 | 01-01-01-tag | run1 | claude-sonnet-4-6 | msgbatch_01JFBCNqnu1cwXyqmEKLHQYF | 4 分 30 秒 | 790,370 | 328,227 | $3.65 | 已取代（song-288 平台失敗，整批重跑驗證） |
| 2026-08-05 | 01-01-01-tag | run1 | claude-sonnet-4-6 | msgbatch_01VSDneWuSbf8mShA32jiWrX | 6 分 15 秒 | 790,370 | 326,193 | $3.63 | 已取代（措辭修訂後全體重跑） |
| 2026-08-05 | 01-01-01-tag | run1-rescue-288 | claude-sonnet-4-6 | msgbatch_019Hq6bNVXVmp4DjRZ2cgVda | 2 分 5 秒 | 1,015 | 376 | $0.01 | 已取代（措辭修訂後全體重跑，該首原生通過）|
| 2026-08-05 | 01-01-01-tag | run1 | claude-sonnet-4-6 | msgbatch_01VgZ77KAPGWmuu3PnQFqZ7Q | 7 分 1 秒 | 794,913 | 326,435 | $3.64 | 現行 |
| 2026-08-05 | 01-01-01-tag | run2 | claude-sonnet-4-6 | msgbatch_01TLFey3L4fimKxcebTZQGYn | 4 分 21 秒 | 794,913 | 328,324 | $3.65 | 現行 |
| 2026-08-05 | 01-02-01-merge | run1 | claude-sonnet-4-6 | msgbatch_01BvYMFmH8zrUq9SNxWSNba7 | 9 分 14 秒 | 46,454 | 60,974 | $0.53 | 已取代（完整分割驗證不過：漏 366、重複分派 511、撞名 4） |
| 2026-08-05 | 01-02-01-merge | run1 | claude-opus-5 | msgbatch_018TkYpdT3DsZqq2q94FQCUN | — | 0 | 0 | $0.00 | 拒收（temperature 已棄用） |
| 2026-08-05 | 01-02-01-merge | run1 | claude-opus-4-8 | msgbatch_018Wuux4adz5mWSvzJjfgLxb | — | 0 | 0 | $0.00 | 拒收（temperature 已棄用） |
| 2026-08-05 | 01-02-01-merge | run1 | claude-opus-4-6 | msgbatch_01Lmt2j1Txyof9CctUK7CbHA | 12 分 19 秒 | 46,454 | 54,864 | $0.80 | 已取代（圍欄違規；漏 190、發明 151、重複 11） |
| 2026-08-05 | 01-02-01-merge | run1 | claude-opus-5 | msgbatch_012SEfebTnjU5uWN6hhfnhhh | 8 分 45 秒 | 63,368 | 64,000 | $1.92 | 已取代（64k 截斷） |
| 2026-08-05 | 01-02-01-merge | run1 | claude-opus-5 | msgbatch_01Wi9xEoQKCy1nZK6myVNg77 | 11 分 34 秒 | 63,368 | 70,175 | $2.07 | 已取代（驗證不過：漏 59、發明 140、重複 3） |
| 2026-08-05 | 01-02-01-merge | run1 | claude-fable-5 | msgbatch_01M15hUs8P9FDTqWvAHdc1cA | 32 分 45 秒 | 63,368 | 107,721 | $3.01 | 現行歸檔（JSON 語法毀損，驗證不過） |
| 2026-08-05 | 01-02-01-merge | run1 | claude-fable-5 | msgbatch_012stRP28uuQDQwobm41HMLh | — | 0 | 0 | $0.00 | 拒收（thinking.type.enabled 不支援） |
| 2026-08-05 | 01-02-01-merge | run1 | claude-fable-5 | msgbatch_01KpS7AMx1zAHTcNujgGsouJ | 26 分 28 秒 | 63,368 | 128,000 | $3.52 | 現行歸檔（effort max：128k 全耗於推理，正文空白） |
| 2026-08-05 | 03-01-code | run1 | claude-sonnet-4-6 | msgbatch_01L7VepTxSNz5vruvzzjuL2c | 6 分 36 秒 | 1,247,264 | 492,730 | $5.57 | 36 首輸出遭內容過濾攔阻，待修訂重跑 |
| 2026-08-05 | 03-01-code | 引述減量實驗（36 首）| claude-sonnet-4-6 | msgbatch_01Hskdhi2DkudYmgZhhgFts7 | 3 分 51 秒 | 56,458 | 11,074 | $0.17 | 實驗：每碼一行引述，36 首全數通過過濾；歸檔不入 repo |
| 2026-08-05 | 03-01-code | run1 | claude-sonnet-4-6 | msgbatch_01GG5Ez9KT1pPwtQaY4sW7tv | 4 分 35 秒 | 1,293,724 | 269,166 | $3.96 | 過濾零攔阻；song-168、song-590 因餘額用盡失敗，song-775 拒答 |
| 2026-08-05 | 03-01-code | 101 碼樹狀探測（148 首）| claude-sonnet-4-6 | msgbatch_017jo3E5gWVks9b39iWMTqz3 | 2 小時 11 分 | 385,270 | 79,690 | $0.87 | 實驗：k=100 葉碼＋women-power；零違規碼； 歸檔不入 repo |
| 2026-08-06 | 命名實驗（100 組）| — | claude-sonnet-4-6 | msgbatch_01XSi1YtWzdVyYUzYh7DQRWg | 3 分 5 秒 | 55,090 | 1,168 | $0.09 | 實驗：LLM 命名對照 medoid，未採用；歸檔不入 repo |
| 2026-08-06 | 命名實驗（100 組）| — | claude-fable-5 | msgbatch_01Y8SJj1h1ZuSQRErhqkvgZE | 3 分 2 秒 | 76,211 | 2,049 | $0.43 | 實驗：同上，加禁用 themes；未採用；歸檔不入 repo |
| 2026-08-06 | 03-01-code | run1 | claude-sonnet-4-6 | msgbatch_01GS1opvurvsf62oknnQxhtx | 3 分 46 秒 | 1,625,458 | 362,759 | $5.16 | 現行（101 碼；883 首全數有效，零攔阻） |
| 2026-08-06 | 03-01-code | run2 | claude-sonnet-4-6 | msgbatch_01CxnwNLWzZbRpZK7UAdpb8i | 5 分 22 秒 | 1,625,458 | 364,098 | $5.17 | 現行（101 碼；883 首全數有效，零攔阻） |
| 2026-08-06 | 03-02-arbitration | — | claude-sonnet-4-6 | msgbatch_019xcQXwrbwDGFc9nE5M8AjE | 4 分 0 秒 | 763,193 | 42,389 | $1.46 | 已取代（2 首遭內容過濾攔阻、13 首輸出夾帶散文；定義檔修訂後重跑） |
| 2026-08-06 | 03-02-arbitration | — | claude-sonnet-4-6 | msgbatch_01N7bDbXRSfAVUzzaj2thKeR | 4 分 20 秒 | 781,037 | 39,315 | $1.47 | 現行（644 首全數有效，零攔阻；保留 1,481／送裁 1,699） |
| 2026-08-06 | 03-code | run3 | claude-sonnet-4-6 | msgbatch_01KnkCaGETnFJrPddrxZTYHA | 6 分 26 秒 | 1,625,458 | 363,840 | $5.17 | 現行（101 碼；883 首全數有效，零攔阻） |

累計支出：$63.22。
