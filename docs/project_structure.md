# 專案目錄結構

（2026-07-30 討論定案版；分析管線已改為 API script 路線，
定義檔不再放 `.claude/agents/`）

```
pop-fem-audit/
├── README.md                  # 專案說明、重現步驟
├── CLAUDE.md                  # 極簡工作規範（subagent 會讀到，
│                              #   絕不放理論、codebook、預期結果）
├── .gitignore                 # data/lyrics/、.env、scratch
├── conference_abstract.md     # pilot 摘要（投稿版）
├── data/
│   ├── yearend_hot100_2016_2025.csv   # 原始榜單（唯一手放原始檔）
│   ├── songs_unique.csv               # 衍生：去重歌曲表（song id）
│   ├── artists_gender.csv             # 衍生：演唱者性別後設資料
│   └── lyrics/                        # 歌詞快取（gitignored，版權）
├── prompts/                   # LLM 定義檔（逐字作為 system prompt）
│   └── <task>_v<N>.md         #   版本化：screen_v1.md、judge_v2.md…
├── scripts/                   # deterministic Python scripts
│   │                          #   （runner、抓歌詞、統計、圖表）
│   └── run_llm.py             # API runner：2+1 協定、Batch API、
│                              #   自動寫入 runs/
├── runs/                      # 每次執行的完整稽核紀錄（進 git）
│   └── <階段>/<日期>-<定義檔版本>/
│       ├── prompt.md          # 當次定義檔快照（自我完備）
│       ├── run1.jsonl         # 第一次執行原始輸出
│       ├── run2.jsonl         # 第二次執行原始輸出
│       ├── arbitration.jsonl  # 仲裁輸出
│       └── meta.json          # model ID、temperature、時間戳、
│                              #   batch ID、一致率
├── results/                   # 仲裁後最終衍生表（論文引用來源）
├── docs/
│   ├── research_plan.md       # 研究步驟規劃（本檔之姊妹篇）
│   ├── project_structure.md   # 本檔
│   ├── codebook.md            # 人工編碼手冊（版本由 git 管理）
│   ├── decision_log.md        # 決策日誌：每次改定義檔的原因
│   └── methodology.md         # 方法細節（全文方法節底稿；
│                              #   映射分析方法須在看結果前寫定）
└── paper/
    └── full_paper.md          # 全文
```

## 設計理由

- **`runs/` 自我完備**：每個執行目錄含定義檔快照 + 原始輸出 +
  meta，讀者不需 git 考古即可稽核任一筆結果。
- **`runs/`（原始稽核資料）與 `results/`（最終表）分離**：
  論文只引 `results/`，其來源可回溯至 `runs/`。
- **`prompts/` 用檔名版本化**（不只靠 git 歷史）：定義檔版本是
  論文附錄的引用單位，須可直接指名（如 judge_v2.md）。
- **API 金鑰**放 `.env`（gitignored），script 由環境變數讀取，
  絕不寫入 repo。
- **CLAUDE.md 極簡**：實測證實 Claude Code subagent 會繼承專案
  CLAUDE.md 全文，故其中只放工作流程規則，領域知識一律放
  `docs/`（subagent 不會自動讀到）。
