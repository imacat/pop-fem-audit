# 流行音樂中「女性力量」語彙的挪用與污染

## ── 以 Billboard Year-End Hot 100（2018–2025）為例的內容分析

**投稿類別**：研究論文／口頭報告
**關鍵字**：女性主義內容分析、流行音樂、empowerment、商品化、AI 文本分析、語言挪用

---

## 摘要

本研究以 2018–2025 年 Billboard Year-End Hot 100（共 684 首歌）為素材，
檢視「women-power-and-empowerment」（女性力量／賦權）這個流行音樂主題標籤
在當代主流商業音樂中的使用實況。透過 AI pipeline 抽取主題標籤，再以人工
逐首審視全部被標記為「女性力量」的 62 首歌，發現其中 **44% 屬於「假女性
力量」**——表面採用 pro-women 詞彙（empowerment、boss bitch、queen、
femininity），實質敘事框架卻是父權保護、物化、競爭性貶低其他女性，或將
「賦權」等同於採用男性饒舌階層的炫耀邏輯。本研究歸納出五種「假女性力量」
類型，並就「pussy」一詞作為女性代稱（metonym）的使用進行附加分析，發現
此種以身體部位代稱人格的修辭橫跨男女歌手。研究亦發現大型語言模型（LLM）
對此種標籤污染存在系統性盲點，並提出框架感知（frame-aware）的修正方法
作為方法學貢獻。

---

## 一、研究問題

「賦權」（empowerment）一詞自 1980 年代女性主義論述進入主流流行文化
以來，已逐步被市場語彙化。Beyoncé、Lizzo、Megan Thee Stallion 等女
性藝人的「女性力量」框架被廣泛流通，唱片公司、串流平台與商業媒體亦頻繁
以 empowerment、boss、queen、she/her anthem 等標籤行銷女性藝人。

問題在於：**當「女性力量」成為一種行銷標籤時，它指涉的內容是什麼？**

本研究提出兩個具體問題：

1. 當主流商業音樂中一首歌被標記為「女性力量」時，其敘事框架是否實質上
   傳達女性主體性（agency）、自主（autonomy）與獨立（independence）？
2. 若不是，被誤標的內容呈現何種模式？這些模式如何與既有的厭女、物化、
   父權結構關聯？

## 二、研究方法

### 2.1 語料

- **來源**：Billboard Year-End Hot 100（年度終榜），2018–2025 年
- **總數**：684 首歌（含跨年榜重複的歌曲算一筆）
- **歌詞抓取**：Lyrics.ovh、LRCLIB API
- **元資料**：演唱者性別（男 / 女 / 混合團體）、年份、排名、合作署名

### 2.2 主題標籤抽取流程

採用四步驟混合式 AI pipeline：

1. **逐首抽取主題關鍵字**（5–10 個 / 首，由 LLM agent 完成）
2. **同義詞合併**（1982 個原始關鍵字 → 718 個 canonical）
3. **主題分群**（718 個 canonical → 33 個 thematic element bucket）
4. **三角驗證 tagging**：
   - **由下而上路徑**（bottom-up）：透過第 1–3 步歸納
   - **由上而下路徑**（top-down）：另一個 LLM agent 直接讀全文，套用既
     定 33 bucket
   - **逐主題盲審 judge**：對兩條路徑的差異逐一判定保留／剔除

最終產出固定 33 個 thematic element 的 v1 schema。

### 2.3 「女性力量」後驗審查

對全部 62 首被標記 `women-power-and-empowerment` 的歌進行人工逐首審
視：由三個獨立 LLM subagent 分別判定 genuine（真）／peripheral（點綴）
／fake（假），最後人工仲裁；同時對其中出現「pussy」一詞的歌進行修辭
脈絡分析。

### 2.4 「pussy」修辭分類

對全部 684 首歌中含「pussy / pussies」一詞的 53 首唯一歌曲（含跨年
重複共 56 筆），逐詞分類為四種修辭功能：

- **METONYM**：以 pussy 代稱「女人」這個人（不指身體部位）
- **ANATOMICAL**：指涉身體部位本身或性行為
- **COWARD**：作為「膽小鬼」的中性侮辱
- **OTHER**：動物或語境不明

每筆使用另標註：說話者性別（male / female / mixed）、指涉對象
（self / other-women / women-collective-positive / women-collective-negative）。

## 三、主要發現

### 3.1 「女性力量」標籤的污染率：44%

| 分類 | 數量 | 比例 |
|---|---:|---:|
| Genuine（真女性力量） | 28 | 45% |
| Peripheral（pro-women 僅為點綴） | 7 | 11% |
| **Fake（表面 pro-women，實質父權／物化／厭女）** | **27** | **44%** |

近半數被標記為「女性力量」的主流商業歌曲，其敘事框架實際上並未傳達
女性主體性、自主或獨立。

### 3.2 「假女性力量」的五種類型

#### 類型 A：男歌手的騎士保護者敘事（chivalric paternalism）

男性歌手以「我會保護妳」、「我會供養妳」、「沒人能傷害妳」自居，將
女性置於需要男性 wield power on behalf of her 的位置。**權力的源頭
不在女性自己，而在替她出力的男性**。代表案例：Drake & 21 Savage
"Spin Bout U"（"I gotta protect ya"）、Drake "Nice For What"。

#### 類型 B：女歌手以身體部位代稱自我與女性整體

以 pussy / bitch 等性器詞彙作為「女人」的代名詞，看似 reclamation，
但其修辭結構仍內化於男性饒舌階層的詞彙邏輯中。代表案例：Cardi B &
Megan Thee Stallion "WAP"、Megan Thee Stallion "Thot Shit"、
Megan Thee Stallion & Dua Lipa "Sweetest Pie"。

（注意：本研究區分**自指身體**的 pussy 使用——女歌手描述自己身體
本身——與**以 pussy 代稱女人**這種 metonym 修辭。前者是粗俗詞彙
但仍將女人視為主體；後者則將女人化約為其身體部位。詳見 3.3。）

#### 類型 C：用男性指標衡量「賦權」

「Empowerment」被定義為擁有名牌、得到男人的錢、性的支配權、能凌駕
其他女性。這種「賦權」本質是**將既有的（男性建構的）權力／資本指標
讓渡給女性個體去追求**，而非挑戰結構。代表案例：Cardi B "I Like
It"、Cardi B "Up"、Megan Thee Stallion "Savage"、Mary J. Blige
"Juicy"。

#### 類型 D：競爭性貶低其他女性以自抬身價

歌曲表面 assert 女性力量，但其修辭策略是不斷貶低、嘲諷、威脅其他
女性。「我是 queen」的命題往往以「她們是 fake / hoes / pussies」
為陪襯前提。代表案例：Latto "Big Energy"、Nicki Minaj & Ice
Spice "Barbie World"、Ice Spice "Princess Diana"、GloRilla &
Cardi B "Tomorrow 2"。

#### 類型 E：直接複製男性饒舌階層

歌詞結構幾乎是男性饒舌歌手歌詞的字面翻版（炫富、嗆對手、宣告 turf、
sexual dominance），只是性別主詞置換。**這不是 reclamation 而是
horizontal substitution**。代表案例：GloRilla "Yeah Glo!"、Nicki
Minaj "FTCU"、GloRilla & Megan Thee Stallion "Wanna Be"、
Sexyy Red "Get It Sexyy"。

### 3.3 「Pussy」作為女性代稱：跨性別的內化

對 53 首唯一歌曲的逐詞分析發現：

- **Dominant METONYM 歌曲**：8 首（pussy 主要功能是代稱女人）
- **Dominant ANATOMICAL 歌曲**：32 首（指涉身體 / 性行為）
- **Dominant COWARD 歌曲**：13 首

以 pussy 代稱女人這種 metonym 修辭出現於兩類說話者：

**男性歌手**（將女人化約為其性器）：
- Drake — "Life Is Good"（2020）、"Spin Bout U"（2023）
- The Weeknd — "Heartless"（2020，同一首中 2 次）
- 21 Savage — "redrum"（2024）
- Bryson Tiller — "Whatever She Wants"（2024）

**女性歌手**（用 pussy 貶低、排序其他女性）：
- Cardi B — "Tomorrow 2"（2023）
- GloRilla — "Wanna Be"（2024）、"Yeah Glo!"（2024）

值得注意的是：**女性歌手以 pussy 代稱「自己作為女性主體」**
（reclamation 用法，target = women-collective-positive）的案例
——例如 Megan Thee Stallion 在多首歌中的女性主體宣告——本研究**不
列入物化清單**，因其修辭結構是 assert woman as subject，而非
reduce woman to organ。

但 GloRilla、Cardi B 在上述歌曲中的 pussy 使用，是用此詞**對其他
女性進行排序與貶低**——「她們是 pussies」、「真 pussy 在這裡」——
此即類型 D 與類型 E 的修辭操作。**身體部位代稱人格的修辭一旦進入
女性互貶的邏輯，仍是女性物化框架的延續，不因說話者為女性而免疫。**

### 3.4 LLM 內容分析的系統性盲點

追溯被誤標為「女性力量」的 27 首假歌曲，其標籤來源分布：

| 標籤來源 | 數量 |
|---|---:|
| **由下而上 + 由上而下兩條路徑都同意**（直接進入 agreed，judge 看不到） | **24 / 27** |
| 僅由下而上路徑提出 | 3 / 27 |
| 僅由上而下路徑提出 | 0 / 27 |

**89% 的假標籤是兩條結構不同的 LLM 路徑「共同同意」的結果。**

這個發現挑戰了「triangulation 透過路徑差異對抗單一路徑偏誤」的方法
學假設。當兩條路徑都跑在同一個 LLM 家族（本研究使用 Anthropic 的
Sonnet 模型）上時，它們**共享表面詞彙的 pattern-match 偏誤**——只要
歌詞包含「女性主體 + 提及女性議題 + 強勢語氣」這個表層組合，兩條路徑
都會傾向標記為「女性力量」，無論敘事框架實際是父權還是物化。

這呼應 Bender、Gebru 等學者對大型語言模型 stochastic parroting
特性的批判：模型內化的是訓練語料裡「empowerment 該長什麼樣子」的
表層共識，而這個共識本身就是被市場去政治化過的。

## 四、討論

### 4.1 「女性力量」作為去政治化的市場符號

本研究的核心發現可以這樣概括：在當代主流商業音樂的標籤生態中，「女性
力量」作為符號的流通已經與其原初的女性主義內涵嚴重脫鉤。**Empowerment
這個詞彙本身的存在不再保證敘事框架是賦權的**——它甚至常與最徹底的
父權／物化框架共存於同一首歌。

### 4.2 「反向挪用」的悖論

特別值得女性主義關注的是「類型 E」現象：女性饒舌歌手大規模採用男性
饒舌階層的修辭範式（炫富、嗆對手、性支配、體型／外貌互貶）作為
「empowerment」的表現。這種操作可以從兩個對立的角度詮釋：

- **解放詮釋**：女性奪取了原本被男性壟斷的 assertive 修辭空間；
- **內化詮釋**：女性內化了 hegemonic masculinity 的成功標準，把它
  當作「女性也能達到」的目標，而**未挑戰這個標準本身**。

本研究傾向後者詮釋，理由是：類型 E 的歌曲幾乎全數同時包含類型 D
（競爭性貶低其他女性）與類型 B（pussy 代稱女人），其結構整體性地
複製了男性饒舌的厭女語法，而非挑戰它。**「女性也能做這件事」不等於
「這件事被女性主義化了」**。

### 4.3 身體部位代稱的跨性別內化

類型 B 與「pussy 作為女人代稱」的修辭，是上述內化最具體的語言層證
據。當女性歌手在歌詞中說「real pussy in this bitch」（真女人在
這裡）時，「真女人」這個概念本身就是**用男性凝視的詞彙來定義的**——
女人 = pussy。這個等式在女性說話者口中重述，形式上的反轉（女性
agency）並沒有改變內容上的物化（女人是其性器）。

## 五、方法學貢獻

### 5.1 LLM 共同盲點不是絕對極限，而是提示問題

本研究進一步測試了一個 prompt 修正：在 by-down/top-down agent 與
judge agent 的提示中加入：

1. **框架原則（frame vs vocabulary）**：任何主題的判定應看敘事
   框架，不只看詞彙；
2. **權力來源測試**（針對 women-power 專用）：權力來自女性自己，
   還是來自他者（男性、男性指標、貶低其他女性）？
3. **Agreed 例外規則**：對 women-power 此標籤，judge 可以例外推翻
   agreed 的保留決定。

對全部 684 首歌重新跑這個修正版 pipeline 後：

- 28 首假女性力量被移除
- 標籤的「假率」由 44% 降至 5% 以下
- 對 v1 漏掉的 19 首真實女性力量歌曲被補回

這顯示：**LLM 的「共同盲點」不是模型架構的絕對極限，而是「沒有提示
要找什麼，模型就不會找」的問題**。給予明確的框架感知提示後，同一個
模型可以執行 frame-level 分析。

### 5.2 對人文／性別研究使用 AI 工具的啟示

本研究實證地呈現了兩個對未來方法學設計重要的點：

1. **路徑結構不同 ≠ 獨立**：在同一個 LLM 家族上，方法上不同的多
   條路徑仍共享訓練語料層次的偏誤。真正的「triangulation」需要
   model diversity（跨家族），不只方法 diversity。
2. **Frame-aware prompting 是可行且必要的**：對於 women-power
   這類「市場已先一步污染」的概念，分析者必須事先清楚 articulate
   什麼算真、什麼算假，並把這個區分寫進 prompt。

## 六、限制

1. **代表性**：Billboard YE Hot 100 反映美國主流商業市場，不代表
   獨立、地下、非英語流行音樂；
2. **語言限制**：拉丁語系歌曲的歌詞分析深度受限；
3. **schema 主觀性**：33 個 bucket 為 AI 一次性歸納，非學術共識
   分類；
4. **跨文化遷移**：本研究的「假女性力量」類型主要出自美國黑人女
   饒舌歌手脈絡，其結構與台灣／華語流行音樂中的相應現象有何異同，
   是後續研究的重要方向。

## 七、結論

主流商業流行音樂中的「女性力量」標籤已被市場語彙化到與女性主義原
初內涵嚴重脫鉤的程度。在 2018–2025 年 Billboard 年終榜上，**44%
的「女性力量」歌曲實質框架是父權、物化或厭女的**。被誤標的歌曲呈
現五種類型：男性騎士保護敘事、女性身體部位代稱、男性指標衡量賦權、
競爭性貶低其他女性、直接複製男性饒舌階層。

這個標籤污染現象的存在本身，就是當代「女性力量」作為市場符號去政治
化的最佳證明。當「empowerment」可以同時指涉真實的女性主體性宣告
（如 Sabrina Carpenter "Feather"、Miley Cyrus "Flowers"、HUNTR/X
"Golden"）與「我比其他婊子更高級」這類內化於男性凝視框架的競爭性
炫耀（如 GloRilla "Yeah Glo!"、Latto "Big Energy"），這個詞已經
失去了區辨意義。

對 AI 內容分析方法學而言，本研究指出共同 LLM 盲點是 prompt 問題
而非模型極限：給予明確的框架感知提示後，同一個模型可以做 frame-level
分析。這對未來在性別研究、文化研究領域使用 AI 工具的學者而言，是一
個具體可行的修正路徑。

---

## 附錄：分析資料

- 完整 62 首 women-power 歌曲分類資料（genuine / peripheral / fake）：
  `theme_extraction/women_power_analysis/final_classification.json`
- 53 首 pussy 修辭使用分類：`pussy_usage_analysis.json`
- 33 個 thematic element schema（v1）：`theme_extraction/v1_schema.json`
- v1.1 修正後全量重跑統計：`theme_extraction/v1_1_summary.json`

## 投稿資訊（待確認）

- **目標研討會**：女學會年會
- **論文長度**：（依會議要求調整，本檔約 3,400 字，可作為 extended
  abstract 或論文初稿大綱）
- **作者**：（待補）
