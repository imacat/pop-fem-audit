# 專案目錄結構

（2026-07-30 討論定案；2026-07-31 更新為 tools/ 子專案與
SQLite 工作儲存架構）

```
pop-fem-audit/
├── README.md                  # 專案說明、重現步驟
├── CLAUDE.md                  # 極簡工作規範（subagent 會讀到，
│                              #   絕不放理論、codebook、預期結果）
├── .gitignore                 # captures/lyrics/、.env、scratch
├── data/                      # 依生命週期分層（文字格式）
│   ├── source/                # 源頭：手放後不動
│   │   └── yearend_hot100_2016_2025.csv   # 原始榜單
│   ├── captures/              # 外部捕捉：只由 fetch 命令與
│   │   │                      #   私人匯入腳本寫入
│   │   ├── artists-wikidata.csv           # Wikidata 快照
│   │   ├── lyrics-provenance.csv          # 歌詞出處
│   │   └── lyrics/                        # 歌詞 .txt 快取
│   │                                      #   （gitignored，版權）
│   ├── manual/                # 人工著作：只由研究者手寫
│   │                          #   （黃金標準編碼等）
│   └── derived/               # 衍生：只由 build-db 寫入
│       ├── songs.csv          # 歌曲報表（人讀；進 git）
│       └── artists.csv        # 歌手報表（人讀；進 git）
├── prompts/                   # LLM 定義檔（逐字作為 system prompt）
│   └── <步>-<次步>-<task>.md  # 01-tag.md、03-code.md
│                              #   （步內僅一個執行時省略次步）
│                              #   不帶版本號，版本即 git 歷史
│                              #   （編號的所指是工序：確定性
│                              #   的步驟 2 無定義檔仍佔一號；
│                              #   補零只為排序）
├── tools/                     # 輔助工具子專案（src-layout）
│   ├── pyproject.toml         #   發行名 pop-fem-audit-tools；
│   │                          #   pip install -e tools/ 安裝
│   ├── README.rst  LICENSE  MANIFEST.in  .env.example  .gitignore
│   ├── docs/                  # Sphinx API 文件
│   ├── instance/              # SQLite 工作儲存（generated、
│   │                          #   gitignored；含歌詞全文）
│   ├── src/pop_fem_audit_tools/
│   │   ├── __main__.py        # 套件 CLI 進入點（分派子命令）
│   │   ├── commands/          # CLI 子命令模組（登記於 __init__）
│   │   │   ├── build_db.py    # build the SQLite working store
│   │   │   │                  #   from the inputs
│   │   │   ├── export_llm_input.py # export the LLM input JSONL
│   │   │   │                       #   (lyrics only) from the
│   │   │   │                       #   working store
│   │   │   ├── fetch_artists.py # fetch artist metadata from
│   │   │   │                    #   Wikidata into the snapshot CSV
│   │   │   ├── fetch_lyrics.py # fetch missing lyrics from the
│   │   │   │                   #   public APIs into the lyrics dir
│   │   │   ├── cluster_keywords.py # pool the tagging runs'
│   │   │   │                       #   keywords and cluster them
│   │   │   │                       #   into the codes (step 2)
│   │   │   └── run_llm.py     # API 執行器：一份定義檔＋一份輸入
│   │   │                      #   →歸檔至指定目錄（Batch API）；
│   │   │                      #   多次執行的計票由獨立子命令承擔
│   │   ├── config.py          # pydantic-settings 設定（.env）
│   │   ├── database.py        # SQLAlchemy engine / session / Base
│   │   ├── models.py          # SQLAlchemy ORM 資料模型
│   │   └── utils.py           # 共用工具（format_duration）
│   └── tests/                 # 單元測試（unittest）
├── runs/                      # 現行執行的完整稽核紀錄（進 git；
│   │                          #   重跑同一 run 須明示 --replace）
│   ├── <步驟名>/              #   一步一個目錄（如 03-code）
│   │   └── run<N>/            #   LLM 步驟：每個 run 一份自我
│   │       ├── prompt.md      #   完備歸檔（定義檔快照）
│   │       ├── output.jsonl   #   該次執行原始輸出
│   │       └── meta.json      #   model ID、temperature、時間戳、
│   │                          #   batch ID、token 用量
│   └── 02-cluster/           # 確定性步驟：無執行變異，
│                              #   不分 run<N> 層
├── results/                   # 論文引用的報表 CSV（export 產出；
│                              #   「可再生仍 commit」的唯一例外）
├── docs/
│   ├── research-plan.md       # 研究步驟規劃（本檔之姊妹篇）
│   ├── project-structure.md   # 本檔
│   ├── codebook.md            # 人工編碼手冊（版本由 git 管理）
│   ├── decision-log.md        # 決策日誌：每次改定義檔的原因
│   ├── run-costs.md           # 每次執行的 token 用量與費用
│   └── methodology.md         # 方法細節（全文方法節底稿；
│                              #   映射分析方法須在看結果前寫定）
└── paper/
    ├── abstract.md            # 摘要
    └── 流行音樂中「女性力量」….odt  # 全文
```

## 設計理由

- **`runs/` 自我完備**：每個執行目錄含定義檔快照 + 原始輸出 +
  meta，讀者不需 git 考古即可稽核任一筆結果。
- **`runs/`（原始稽核資料）與 `results/`（最終表）分離**：
  論文只引 `results/`，其來源可回溯至 `runs/`。
- **`prompts/` 檔名不帶版本號**：版本即 git 歷史，失敗的
  版本不保留；論文引用的單位是 `runs/` 內隨執行保存的定義檔
  快照（每個執行目錄自我完備），不需檔名可指的版本名。
- **工作儲存的資料表**：`songs`、`chart_entries`、`artists`、
  `song_artists`、`codings`（定案編碼：一歌一標籤一列，`quotes`
  存該標籤所據的歌詞引述，多句以 `|` 相接）。定案表
  `results/codings.csv` 經 `build-db --codings` 匯入，與其餘資料
  同一交易，儲存不會半建；詳見 `research-plan.md`「資料儲存與
  模型」。
- **Commit 判準**：能由「committed 輸入＋程式」決定性再生者不
  commit（SQLite 工作儲存、LLM 輸入檔）；源頭、捕捉、人工著作
  一律以文字 commit。「可再生仍 commit」的例外有二：
  `results/` 報表（引用穩定性、審稿人零門檻、撰稿期可 diff）
  與 `data/derived/` 人讀報表（與工作儲存同一動作產出，稽核
  鏈無中間空缺）。詳見 `research-plan.md`「資料儲存與模型」。
- **設定**經 pydantic-settings 統一：`.env`（gitignored，範本
  `tools/.env.example`）供應 `SQLALCHEMY_DATABASE_URL` 與
  `ANTHROPIC_API_KEY`，絕不寫入 repo。
- **CLAUDE.md 極簡**：實測證實 Claude Code subagent 會繼承專案
  CLAUDE.md 全文，故其中只放工作流程規則，領域知識一律放
  `docs/`（subagent 不會自動讀到）。
