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

## 2026-07-31

- **專案英文名定為「A Feminist Audit of Pop Music」**：明示
  女性主義立場，「audit」兼指對歌曲與對 LLM 標籤系統的稽核，
  並與縮寫 `pop-fem-audit` 對應。
- **程式碼收整為 `tools/` src-layout 子專案**：發行名
  `pop-fem-audit-tools`、import 套件名 `pop_fem_audit_tools`、
  description「Tools for A Feminist Audit of Pop Music.」；
  以 `pip install -e tools/` 安裝、`python -m
  pop_fem_audit_tools.run_llm` 執行；相依套件記於
  `pyproject.toml`（`requirements.txt` 移除）；Sphinx 文件
  暫緩。理由：後續多支程式將共用程式碼，套件化後測試可用
  正常 import；目錄名 `tools/` 經無脈絡的獨立 subagent 命名
  評估選出，最誠實反映「服務研究的輔助工具」定位——研究
  本體在根目錄的 prompts/、runs/、results/，程式只是配套。
- **CLI 入口改為套件層級 dispatcher**：dispatcher 為單一
  入口，`run_llm.py` 的 entry point 移除；有兩種等價呼叫
  形式——`python -m pop_fem_audit_tools run-llm ...` 與
  console script `pop-fem-audit-tools run-llm ...`
  （`[project.scripts]`）。理由：後續多支工具共用單一入口，
  `--help` 可列出全部子命令，重現文件穩定。
- **資料儲存架構定案**：commit 判準——凡能由「committed 輸入＋
  committed 程式」決定性再生者不 commit；源頭、外部捕捉、人工
  著作以文字格式 commit。工作儲存採 SQLite 單檔
  （`tools/instance/`，generated、不進 git；歌詞全文入 DB 故無
  版權疑慮），schema 以 SQLAlchemy 2.0 typed ORM 定義，設定經
  pydantic-settings（`.env`）。`results/` 報表 CSV 為「可再生仍
  commit」的唯一例外，理由：論文引用穩定性、審稿人零門檻、
  撰稿期數字變動可 diff。（本條經多輪辯證後定案，推翻 Claude
  最初的全 CSV 方案。）
- **資料模型**：songs、chart_entries（1—N）、artists、
  song_artists（M—N：角色、署名順序）、lyrics（1—1）；領域
  不變量檢查內建 `build-db`，違規即失敗。
- **歌手背景擴充與防火牆**：歌手資料擴為實體表（QID、性別、
  型態、曲風、國籍），women-power 候選的歌手另做深度背景
  （族裔以公開自我認同為準、音樂場景），供人工解讀與論文
  討論；**歌手背景絕不進 LLM 輸入**（歌詞-only），避免光環
  偏誤污染條件 A/B 實驗。
- **沿用先導研究歌詞捕捉**（lyrics.json，684 首，2018–2025）：
  只匯入識別欄位與歌詞本文，pilot 分析欄位不匯入；以
  (year, rank) 精確匹配。出處記於 `lyrics_provenance.csv`：
  source（原始 API）與 method（pilot-import / api-fetch）
  兩層；取得日期不可考者不假造，僅記可證上界。
- **`run_llm` 改走 pydantic-settings 統一設定**（刪手寫 .env
  parser），與 `config.py` / `database.py` 一致。
- **`lyrics` 表併入 `songs.lyrics` nullable 欄位**（資料模型由
  五表改四表）。理由：1—1 關係在此量級下獨立成表只有正規化
  慣性，nullable 欄位更簡單；「未取得」以 NULL 表達，語意
  等價。

## 2026-08-01

- **引擎獨立性以 PostgreSQL/SQLite 為範圍**（MySQL 的 VARCHAR
  長度限制不處理）。
- **`build-db` 的重置改用逐表 DELETE，不再 drop/create**：
  schema 生命週期歸 migration 管，build-db 只管資料。連帶
  效果：重置成為純 DML,全程單一交易、驗證通過才 commit——
  建置失敗時前一版資料完好。首次執行仍以 create_all
  （checkfirst）補缺表。
- **song/artist ID 由 build-db 顯式指派**（首次出現順序 1、2、
  3…），不依賴 autoincrement——PostgreSQL 的 sequence 在
  DELETE 後不重置，顯式指派讓重建決定性跨引擎成立。
- **禁止文字 SQL statement，一律經 SQLAlchemy ORM/Core API**。
  唯一記錄在案的例外：SQLite 的 `PRAGMA foreign_keys=ON`
  （官方建議作法，無非文字 API 可用；SQLite 的 FK 旗標為
  逐連線設定）。裁定其歸屬為連線組態，實作於 `database.py`
  的 `__create_engine`——建 engine 時對 SQLite 註冊 connect
  listener，所有消費者全程生效，不再由 build-db 各自註冊。

## 2026-08-02

- **`import-lyrics` 不設為子命令，pilot 歌詞改以私人腳本
  匯入**。理由：pilot 捕捉檔不隨論文發布，子命令
  形式會在發布的 CLI 裡留下讀者無法執行的死命令——要交待的
  是「沿用 pilot 捕捉」的事實（記於 lyrics_provenance.csv 與
  論文方法節），不是工具本身；工具移出專案，發布管線即
  「讀者可完整執行的程序」。讀者重現歌詞的路徑為
  `fetch-lyrics`，API 漂移造成的差異屬捕捉層的已承認限制。
  provenance 的 method 值域定為
  pilot-import / api-fetch / manual。
- **資料路徑全面改為顯式 CLI 引數**——必要運算元為位置
  引數、選擇性輸入為選項（build-db 吃榜單 CSV 一個位置引數，
  歌詞目錄、Wikidata 快照、overrides 為 `--lyrics-dir`／
  `--wikidata-csv`／`--overrides-csv` 三個選項；fetch-lyrics
  吃歌詞目錄、provenance、缺漏報表三個位置引數；fetch-artists
  吃快照檔；run-llm 吃 runs 目錄），命令與 CWD 無關，且每次
  執行觸碰的檔案完整見於指令本身。省略選項即不載入該捕捉層；
  給了選項而路徑不存在即建置失敗，取代原本的默默跳過。理由：
  settings 的 `.env` 依 pydantic 慣例讀自 CWD（約定
  `tools/`），資料路徑原以 repo 根為 CWD，兩者衝突；顯式引數
  消滅隱性 CWD 契約，亦拒絕以父目錄推導兄弟檔案的隱性慣例。
- **`data/` 依生命週期分三層**：`source/`（源頭，手放後不動）、
  `captures/`（外部捕捉，只由 fetch 命令與私人匯入腳本寫入）、
  `manual/`（人工著作，只由研究者手寫；之後的黃金標準編碼
  亦居此）。理由：三種生命週期混住一層，目錄無法傳達「誰可以
  寫哪裡」；顯式引數化後搬遷零程式改動。
- **源頭榜單 CSV 全面對齊 Billboard 年終榜發布版**（修正
  203 列）。語料源頭定義為「年終榜發布當時的印法」，以
  Wayback Machine 發布時快照逐字轉錄（2016–2018 原沿
  Wikipedia 改寫慣例）；年終原文殘缺或有疑問者，以當年週榜
  掛名為準（唯一適用例：2016#87〈All the Way Up〉）。
- **歌名正規化採 canonical artist credit 對照表**：同一首歌
  因署名字串寫法不同而分裂者，以明示對照表合併；歌曲身分＝
  （原始歌名，對照後署名字串），不解析署名——拆解機器不進
  歌曲身分判定，對照表即完整可稽核清單。
- **歌手名單拆解規則定案**：署名列出成員的團體只留成員
  （冒號與括號兩型）；名字內含連接詞的單一藝人入保護名單；
  規則無法表達的個案入例外表；人名連寫的二人組拆成個人；
  僅以團名掛名的團體維持單一實體，屬性留待 fetch-artists
  與人工 overrides。完整清單見 `build_db.py`。
- **歌手名正規化**：歌手名大小寫不敏感歸併、存首見拼法；
  正名表（casefold 鍵→官方拼法）存官方拼法，含跨拼法合併
  ye→Kanye West。
- **`data/` 增設 `derived/` 衍生層**：`build-db` 建置工作儲存
  的同一動作產出兩張人讀報表（songs.csv、artists.csv）並
  commit——與 SQLite 同交易語意、驗證通過才寫檔，稽核鏈
  「committed 輸入＋程式→CSV」無中間空缺；為「可再生仍
  commit」的第二例外。報表不含資料庫 ID（內部參照，資料
  改版會重排，不供引用）；關係以內嵌字串呈現——`/` 連同
  一首歌的多次上榜、`|` 連不同歌曲——欄位一律字母序。
- **歌手正名表全面改存官方拼法**：變音符號一律恢復
  （Billboard 印法慣性去符號，共 12 筆，如 Aminé、Jhené
  Aiko、Silentó）；二人組拆名改存成員全名（Dan Smyers、
  Shay Mooney）；官方大小寫 3 筆（Cris MJ、Mariah the
  Scientist、Surf Mesa）。官方拼法逐筆以 DSP 官方頁查證
  （維基百科／Wikidata 的大小寫是其自家規範，不作準）；
  查證亦確認 Tones And I 的 chart 印法即官方寫法，不改。
- **`fetch-artists` 解析演算法定案**：改用 WDQS 的 SPARQL
  索引查詢（不依賴搜尋排名、不用 LCASE——實測會逾時）。
  步驟：(1) 歌手名與 label／alias 精確比對（@en＋@mul 兩層）
  取候選，型態限人類∪音樂團體子樹∪original cast；(2) 唯一
  即定案；(3) 歧義以上榜歌曲佐證——歌名精確比對取歌曲條目
  的 P175 演出者（含其 P527 成員）與候選交集；(4) 再落空則
  反向錨定：候選（含所屬團體）演出過的歌曲以 casefold 比對
  歌名；(5) 均落空記查無並續行。每步須恰一命中才選定，
  實測零錯選。Last-resort 釘定表僅一筆（Pinkfong——唯一
  P31 為品牌的上榜演出者，型態閘門依設計排除）。暫時性
  故障（429／5xx／讀取逾時）退避重試，重試盡記 error 列；
  not found 專指程序查證後無所得。全量實跑 469 位全數
  解析且與人工查證的 QID 逐筆相符；首次快照隨本次入
  捕捉層。
- **先補完 Wikidata、再捕捉快照**：歌手資料查證做在上游——
  以 subagent（`artist-wikidata-updater` 定義檔）逐位查證
  快照欄位（P21、P31、P136、P27／P495，新條目加 P106）並
  草擬附來源的 QuickStatements，由研究者本人審摘要、以本人
  帳號執行；編輯沉澱後重跑 `fetch-artists`，Wikidata 容不下
  的判斷才入 overrides。理由：修在上游全網受益，編輯史與
  來源公開可稽核，快照乾淨、overrides 縮小；論文方法節揭露
  「捕捉前經研究者查證補完」。性別以公開自我認同為準，
  推測不確定且無佐證者列疑慮清單；查證屬資料策展而非
  分析，以 Claude Code 輔助、不走分析 API；QS 批次以
  私人工作檔留存，不隨論文發布。

## 2026-08-04

- **移除人工 overrides 層**：`build-db` 刪去
  `--overrides-csv` 選項與套用邏輯，文件同步移除
  `data/manual/artists_overrides.csv`。理由：「先補完
  Wikidata、再捕捉快照」工作流實跑後，469 位歌手全數
  在上游查證補齊，快照即完整，本地覆蓋層已無存在事實；
  `data/manual/` 層保留（供日後黃金標準編碼）。
- **`fetch-lyrics` 加原始署名 fallback**：以第一位 primary
  歌手查詢兩 API 皆落空時，改以拆解前的原始署名字串（缺漏
  報表既有的 `artist_credit`）重查一次；與主查詢同為精確
  查詢，API 順序不變。理由：二重唱／雙掛名歌曲在歌詞 API
  目錄以合體名義建檔（Dan + Shay、Lil Baby & DaBaby），
  單人名查詢必落空；手動模擬證實 fallback 三首全中。
- **歌手型態刪去 mixed 值**：`ArtistType` 只留 solo／group。
  mixed 是先導研究「男／女／混合團體」單一欄位的殘留，
  正式設計拆成 gender＋type 後從未定義其指涉；署名一律
  拆成個人後，男女混合是歌曲層（song_artists＋各歌手
  gender）可推導的事實，不屬歌手實體。非人非團體者
  （Pinkfong）type 留空由人工判定，維持現狀。
- **fetch-lyrics 移除缺漏報表**：刪去 `missing_csv` 位置引數
  與缺漏報表 CSV 輸出。理由：該報表只寫不讀（指令從未讀取
  它），缺漏數字每次執行皆由工作儲存比對歌詞目錄重新算出；
  worklist 角色由重跑冪等指令本身承擔；完整性已由 provenance
  CSV 與 build-db 統計數字佐證；該檔案不承載任何無法重新
  產生的資訊。
