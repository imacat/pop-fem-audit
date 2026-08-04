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
  (year, rank) 精確匹配。出處記於 `lyrics-provenance.csv`：
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
  是「沿用 pilot 捕捉」的事實（記於 lyrics-provenance.csv 與
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
- **`build-db` 匯入重構為兩個 job class**：`SongImporter`
  （榜單 CSV→歌曲身分去重→songs＋chart_entries）與
  `ArtistImporter`（自資料庫依 song ID 讀回署名→拆解→正名
  →去重登記→artists＋song_artists），與 `CSVExporter` 同形
  （建構子收 session、單一公開入口）；命名取 import／export
  對稱，不用 loader（有「載入記憶體」聯想，實為寫入持久
  儲存）。歌手登記改於歌曲全數入庫後第二階段進行，兩塊
  之間不再共享記憶體狀態；各 job 專用的純函數與規則表
  （身分判定、拆解、正名）隨行入 class 作公開 staticmethod
  ／class 常數，「哪個函式屬哪個工作」由 class 歸屬直接
  表達。flush 定為匯入工作的完工契約——entry method 返回
  時自身寫入已可查詢，不再由呼叫者補 flush。捕捉層套用
  （歌詞、Wikidata 快照）隨後同型打包為 `CaptureImporter`
  （單一入口收兩個可省略路徑）。實測重構前後工作儲存
  dump 與衍生報表逐位元組相同。
- **歌手型態刪去 mixed 值**：`ArtistType` 只留 solo／group。
  mixed 是先導研究「男／女／混合團體」單一欄位的殘留，
  正式設計拆成 gender＋type 後從未定義其指涉；署名一律
  拆成個人後，男女混合是歌曲層（song_artists＋各歌手
  gender）可推導的事實，不屬歌手實體。非人非團體者
  （Pinkfong）type 留空由人工判定，維持現狀。
- **獨立驗證步驟解散，不變量檢查歸屬各匯入工作**：榜單
  覆蓋（(year, rank) 網格恰好齊全、無缺漏、無多出、無
  重複）檢在 `SongImporter` 匯入結尾；署名解析結果（至少
  一人、含 primary、名字非空白）檢在 `ArtistImporter` 逐筆
  解析後立即失敗。違規拋 `BuildError` 走既有的失敗路徑，
  `find_violations` 刪除。理由：檢查跟著產生資料的工作走，
  main 不再有驗證分支；逐筆即時失敗使錯誤指向出錯的那筆
  署名。
- **Markdown 檔名一律以 dash 連接**（decision-log.md、
  research-plan.md、project-structure.md 等；與 data/ 層
  CSV 檔名慣例一致），定義檔命名慣例同步改為
  `prompts/<task>-v<N>.md`（如 screen-v1.md），版本庫外的
  私人工作檔一併改名；`conference_abstract.md` 改名並搬入
  `paper/`——它是本次年會實際送出的摘要，與全文同屬投稿
  血脈，不是 `docs/` 的內部工作文件。全 repo 指涉同步更新。
- **fetch-lyrics 移除缺漏報表**：刪去 `missing_csv` 位置引數
  與缺漏報表 CSV 輸出。理由：該報表只寫不讀（指令從未讀取
  它），缺漏數字每次執行皆由工作儲存比對歌詞目錄重新算出；
  worklist 角色由重跑冪等指令本身承擔；完整性已由 provenance
  CSV 與 build-db 統計數字佐證；該檔案不承載任何無法重新
  產生的資訊。
- **新增 `export-llm-input` 子命令**：由工作儲存產出
  `run-llm` 的 JSONL 輸入檔（每筆 `id`＋`content`）；此為
  「歌手背景絕不進 LLM 輸入、歌詞-only」防火牆的執行點
  ——內容只有歌詞，歌曲身分以 `song-<ID>` 不透明鍵放
  `custom_id`，不入訊息本體；ID 由 build-db 決定性指派
  故檔案可再生，依 commit 判準不進 git（且含歌詞全文，
  版權亦不許）；固定匯出全部歌曲，缺歌詞即失敗；單一
  位置引數收輸出檔路徑，文件範例輸出至 `tools/instance/`。
- **指令模組集中為 `commands` sub-package**：五個子命令模組
  移入 `pop_fem_audit_tools.commands`，`__init__` 以
  `from .run_llm import main as run_llm_command` 逐條登記為
  指令清單，`__main__` 只消費此 façade；`_command` 後綴避免
  與子模組同名遮蔽，測試仍以模組屬性風格使用；基礎設施模組
  （config／database／models／utils）留頂層。理由：「指令
  vs 共用底層」由目錄結構直接表達，與「哪個函式屬哪個工作」
  的歸屬原則同型。
- **自然編碼管線四步驟定案**：自由標註（tag，×2 全進池不
  仲裁——自由詞彙兩次輸出無共享比對單位，仲裁即再生成）→
  自然收斂（merge，2+1）→ 強制收斂至 50 內（cap，2+1）→
  以定稿詞彙表全量編碼（code，2+1，附引述，逐首仲裁看
  歌詞）。收斂步驟不看歌詞（目標是產生 codebook 而非編
  碼）；收斂仲裁的紀律：程式先算共識核（凍結）與分歧清
  單，仲裁只裁分歧、不得引入新概念。編碼回歸採 LLM 直接
  編碼為主儀器，理由：唯此能逐標籤附歌詞引述（偏差檢視的
  依據）、標籤是模型對歌曲的直接斷言（批判對象乾淨、不混
  收斂軌跡假影）、詞彙表出自模型自身故無語意干涉；軌跡
  機械對映降為診斷副產品。此設計為對前導研究「映回後未
  對照歌詞」限制的明文改良。
- **2+1 協定適用原則重述**：由「每個 LLM 步驟」修正為
  「輸出可逐項機械比對的步驟」；自由生成步驟改為兩次執行
  進池。CLAUDE.md 同步修訂。理由：自由詞彙步驟強行仲裁
  等於第三次生成，無稽核意義；可比步驟的一致率（逐詞塊、
  逐首）才是有定義的穩定性證據。
- **提示詞只定格式、不定語意**：LLM 定義檔不含任何主題
  定義、判準、範例；研究者判準只住 codebook。理由：研究
  對象是模型以網路語料知識背景所做的自然編碼，先給定義
  即消毒了批判對象。此原則之落實：粒度鎖定 thematic
  keywords（前導研究三粒度比較之繼承，執行前鎖定防事後
  擇優）；收斂輸入不附頻次（頻率的分析角色由編碼步驟承
  擔；頻次誘使頻率剪枝與高頻主題細分）。引述歌詞證據為
  必要輸出——檢視編碼偏差的依據，不屬語意干涉。
- **「女性力量」單目標篩選降級為取樣補漏網**：候選集由
  自然編碼（code 步驟）浮現；單目標篩選僅用於把模型「被
  明示提醒後認得出」的歌撈進人工審視範圍，量測漏標方向
  的偏差，不進偏差統計的定義。「全編碼＋標籤詞提示」混合設計
  取消——既非自然編碼亦非深度判準，量到的東西
  無法解釋。screen 逐首 2+1、不給定義，標籤詞用
  `women-power-and-empowerment`。認清：此編碼是任意的——
  基於研究目的由研究者決定，不是由資料產生（先導研究中的
  來歷已不可考，不宣稱由下而上湧現）。選用理由：複合詞
  同時涵蓋力量宣示與賦權論述兩半概念空間，補漏網寧廣勿
  窄；「empowerment」正是研究對象的市場語彙；不押注單一
  時代慣用語。同義詞清單不採——每多一詞即研究者多塑形
  一分。已知限制：雙管詞語意模糊（無從分辨觸發自哪半），
  僅作召回之用，結果永不進統計的分子分母。標籤詞是
  screen 提示中唯一的語意種子，屬研究者的儀器選擇，據實
  揭露。
- **定義檔命名定案：軌-步前綴、不帶版本號**：
  `prompts/<軌>-<步>-<task>.md`——軌 01＝由下而上自然編碼、
  02＝預先決定的 women-power-and-empowerment 篩選：
  01-01-tag、01-02-merge、01-03-cap、01-04-code、
  02-01-screen；仲裁檔同 prefix 加 `-arb`。檔名不帶版本
  號——版本即 git 歷史，失敗的版本不保留；每次執行的定義
  檔快照隨 runs/ 自我完備，`runs/` 目錄改為
  `<定義檔名>/`——同理不編日期：只存一份，重跑即取代，
  被取代的執行在 git 歷史，時間戳在 meta.json。四次收斂執行（merge ×2、cap ×2）
  各存合併記錄 JSON 隨該次執行入 runs/。
- **`run-llm` 降階為純執行器**：原內建的 2+1 編排（文字級
  一致性判定、固定模板仲裁）拆除；run-llm 只負責「一份
  定義檔＋一份輸入 JSONL，跑 N 次（預設 2、仲裁場合 1），
  歸檔 `runs/<定義檔名>/`（重跑即取代）」。理由：一致性
  判定須逐步驟、結構性（分組比對、標籤集合比對），屬
  確定性腳本的工作；仲裁輸入由比對腳本建構，本身成為
  runs/ 可稽核工件；執行器變小易測。比對／進池／裁決
  套用子命令另行實作。
- **`run-llm` 一次呼叫即一次執行**：`--runs` 與 `--run` 皆不存
  在，完整命令形狀為 `run-llm <定義檔> <輸入檔> <歸檔目錄>`——三個
  必要運算元皆為位置引數（沿 2026-08-02「必要運算元為位置引數」慣
  例），歸檔目錄如 `runs/01-01-tag/run1`，工具內部零 run 概念，
  meta 不記 run 編號；「獨立執行兩次」＝重現命令清單上的兩行命令，
  run 身分只活在命令清單與目錄佈局約定，不在工具內。理由：兩次執行
  互相獨立是方法學宣稱，其證據應由執行結構與重現命令清單自明，不應
  要求讀者讀工具原始碼；歸檔目的地為顯式引數，亦是「資料路徑全面顯
  式化、消滅隱性推導」原則的貫徹。比對子命令驗證兩 run 的定義檔與
  輸入 SHA 一致、缺 run 即失敗。目標目錄已存在即拒絕執行，重跑須明
  示 `--replace`。
- **screen 標籤詞改為 `women-power`（來歷考據定案）**：
  考據先導研究的 local agent 存檔：其第一步指令含數十個
  範例 thematic keywords，其中即有 women-power——為當時
  協作的 Claude Code 依研究者長期表達的關注主動加入
  （研究者端播種，非明示指定）；先導標籤
  women-power-and-empowerment 則是第三步強制合併
  women-power＋empowerment 兩個關鍵字的管線人工產物
  （研究者數月來誤以為是 women-power＋women-empowerment
  之併，至此方明）。修正：探針指向被播種的概念本詞
  women-power，不用合併假影；research-plan 的「來歷不可
  考」敘述同步改為考據結果。附帶認清：先導第一步並非零
  語意提示——此即正式研究「只定格式、不定語意」設計所
  矯正者。
- **定義檔輸出形狀統一與去署名**：LLM 輸出統一為單層
  dict／array——tag、code：關鍵字→引述；merge、cap：
  組名→成員；code-arb：保留關鍵字→仲裁者自己的引述
  （剔除即不列，剔除集合由程式以鍵差推得）；screen 系：
  引述陣列，非空即「有」（present 布林刪除，判斷與依據
  合一）。仲裁輸入一律不含執行別——標示何方主張會誘使
  仲裁者揣測「哪次較可信」，而非就文本裁決。收斂組名採
  自由命名（不限取自成員詞），取命名貼合度；可追溯性由
  軌跡歸檔承擔。
- **定義檔改三層編號**：
  `prompts/<軌>-<步>-<次步>-<task>.md`——次步為步內執行
  順序，明定讀者依循的先後（如 01-04-01-code →
  01-04-02-code-arb）；仲裁檔後綴 `-arb`。
- **收斂演算法：檢視而棄用的方案**：詞彙表建構（merge、
  cap）的重複執行與仲裁，歷經四個方案後全數棄用——
  ①整條管線獨立跑兩遍、於終點仲裁兩份最終詞彙表：兩套
  分類系統互不可比，仲裁淪為第三次建構，一致率無從
  定義。②組對組匹配（以相似度門檻判定兩組是否「同一
  組」）：無原則性答案，門檻任意。③tag 步驟仲裁：自由
  詞彙兩次輸出不共享比對單位，無物可裁（tag 改為兩次
  進池，沿用至今）。④逐對仲裁鏈：交集細分出共識塊、
  分歧塊對三票多數決、union-find 遞移重組、仲裁後命名
  2+1——機械上可行且逐項可驗（共 15 份定義檔，全版
  保存於分支 `tag-algo-13` 備考），但其變異縮減未經證實
  （逐對多數決降低對層變異，遞移閉包卻放大結構層變異，
  淨效果不明），複雜度成本則屬確定，且縮減的是儀器變異
  ——對量測無關緊要的量（見次條）。
- **詞彙表建構改為單次記錄性程序（演算法簡化）**：
  merge、cap 各單次執行、執行內自行命名（具名分組
  輸出），定義檔減為 7 份。2+1 原則改寫：語料層逐首
  判斷（code、screen）一律 2+1；自由生成（tag）兩次
  進池；詞彙表建構單次、全程歸檔。理由：(1) 影響量測的
  是編碼層——詞彙表屬揭露的儀器選擇，凍結後下游同尺量
  到底，其抽樣變異不污染量測；(2) 對齊領域慣行——
  codebook 建構本為單次詮釋程序，信度檢驗施於編碼應用
  層；(3) 複雜仲裁機械無以自證其益（見前條）。驗證改為
  確定性格式檢查（完整分割、組名唯一、cap ≤ 50），違規
  依協定修訂定義檔重跑。
