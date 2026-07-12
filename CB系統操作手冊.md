# 可轉債監控系統 完整操作手冊

> 最後更新：2026-07-11
> 維護者：Peggy (madea104 / madea104-creator)

---

## 1. 系統總覽

目前共有 **三套雲端系統**（GitHub Actions 自動運行，Mac 不需開機）＋ 本機備援：

| 系統 | Repo | 功能 | 更新排程（台灣時間） | 網址 |
|---|---|---|---|---|
| CB 快照儀表板 | `cb-monitor` | 全市場 CB 餘額快照、消化率、目前轉換價、賣回日 | 平日 19:30（快照）＋ 週六 10:00（轉換價） | https://madea104-creator.github.io/cb-monitor/ |
| CB 日報＋新聞 | `cb-monitor-cloud` | CBAS 行情、Gmail 日報、新聞聚合 | 平日 16:35 | https://madea104-creator.github.io/cb-monitor-cloud/ |
| 股票長期走勢 | `stock-viewer` | 287 檔 CB 發行公司 10 年股價（FinMind） | 平日 18:30 | https://madea104-creator.github.io/stock-viewer/ |
| 本機備援 | `~/Project/cb_monitor` | 舊版日報系統（launchd 已停用） | 手動 | 本機檔案 |

⚠️ **常見誤區**：本機 `~/Project/cb_monitor/cb_news.html` 已凍結在 2026-07-07（雲端接管日），看新聞請一律開雲端網址：
`https://madea104-creator.github.io/cb-monitor-cloud/cb_news.html`

---

## 2. cb-monitor（本次新建系統）

### 2.1 檔案結構

```
~/cb-monitor/
├── cb_snapshot_ingest.py        # 每日快照：TPEx OpenAPI → SQLite
├── fetch_conv_prices.py         # 轉換價格歷史：MOPS t120sg06 → SQLite
├── generate_cb_html.py          # 產生單檔 HTML 儀表板
├── cb_openapi.db                # SQLite 資料庫（隨 repo 版本控管）
├── index.html                   # GitHub Pages 首頁（= dashboard）
├── cb_dashboard.html            # 同上，本機檢視用
└── .github/workflows/
    ├── update_cb.yml            # 平日 19:30 快照 + 重建頁面
    └── update_conv_weekly.yml   # 週六 10:00 轉換價刷新
```

### 2.2 資料庫結構（cb_openapi.db）

| 表 | 主鍵 | 內容 |
|---|---|---|
| `cb_snapshot` | (bond_code, snapshot_date) | 每日全市場快照，42 欄（餘額、賣回、評等…），欄位動態擴充 |
| `conv_price` | (bond_code, reset_date, price) | 轉換價格重設歷史（ISO 日期），含已到期 CB |
| `conv_meta` | bond_code | 各檔最後抓取時間與狀態（ok/empty/error） |

### 2.3 儀表板功能

- **消化率量條** = 1 − 餘額 ÷ 發行額（藍條越滿 = 被轉走越多 = 越強勢）
- **Δ餘額**：與前一次快照比較，紅 = 減少（轉換中）
- **目前轉換價**：取重設生效日 ≤ 今日的最新值；**↻ 紅色標記** = 已公告未來重設（滑鼠停留看日期與新價）
- 快速篩選：本次有變動／消化率 >80%／賣回日 180 天內／即將重設
- 點任一列展開：賣回價、承銷商、餘額快照歷史、轉換價格重設歷史

### 2.4 日常手動指令（通常不需要，Actions 會自動跑）

```bash
cd ~/cb-monitor
python cb_snapshot_ingest.py                 # 抓今日快照（含變動偵測輸出）
python fetch_conv_prices.py                  # 增量抓缺漏的轉換價
python fetch_conv_prices.py --stale-days 7   # 連同 7 天未更新的一起刷新
python generate_cb_html.py                   # 重建 cb_dashboard.html
python generate_cb_html.py --out index.html  # 重建 Pages 首頁
git add -A && git commit -m "manual update" && git push
```

---

## 3. 資料來源端點大全（血淚考古成果）

### 3.1 存活且在用的官方端點

| 用途 | 端點 | 方法/參數 | 備註 |
|---|---|---|---|
| 全市場 CB 基本資料＋餘額（每日） | `https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data` | GET，免參數免 token | 407 檔、42 欄；**只有現存 CB、只有當前快照**；轉換價僅發行時 |
| 個股月成交（上櫃） | `https://www.tpex.org.tw/www/zh-tw/statistics/monthlyStock?date=2023&code=7402&response=json` | GET | `response=html` 也可；TPEx 新版 API 通用格式 `/www/zh-tw/.../...?response=json` |
| 個股月成交（上市） | `https://www.twse.com.tw/rwd/zh/afterTrading/FMSRFK?date=1120101&stockNo=xxxx&response=json` | GET | 一次回整年 |
| **轉換價格重設歷史** | `https://mopsov.twse.com.tw/mops/web/ajax_t120sg06` | GET：`encodeURIComponent=1, firstin=true, bond_id=<CB代碼>, step=1, data_type=, date1=, date2=` | ⭐ 核心來源；**含已到期 CB**；來自舊系統 `fill_missing_conv.py` |
| CB 餘額月報（單檔單月，含轉換張數流量） | `https://mopsov.twse.com.tw/mops/web/ajax_t47sb18` | 兩段式 POST，見 3.3 | 歷史回填用（尚未建自動化） |
| CB 基本資料（發行辦法） | `https://mopsov.twse.com.tw/mops/web/ajax_t47sb07` | 兩段式 POST，見 3.3 | 無轉換價欄位（發行辦法是 PDF） |
| CBAS 承作餘額 | TPEx OpenAPI（swagger 內搜「可轉債資產交換」） | GET | 未接入，備用 |
| CBAS 行情 | `https://cbas16889.pscnet.com.tw/api/CbasQuote/GetIssuedCBSchedule` | GET，需 Referer header | cb-monitor-cloud 在用 |

### 3.2 已死亡端點（勿再嘗試）

- ❌ TPEx 舊版網頁 `www.tpex.org.tw/web/...`（2025-06 全面下線，回新版空殼）
- ❌ `wwwov.tpex.org.tw`（舊版鏡像，同期停用）
- ❌ FinMind CB 三個 dataset（`TaiwanStockConvertibleBond*`）：**需付費 Sponsor 等級**
- ❌ money-104.com：需登入＋reCAPTCHA；thefew.tw/cb：會員牆，不當爬蟲對象

### 3.3 MOPS 舊版（mopsov）呼叫要訣

MOPS 是活化石，每頁參數不同，重點筆記：

1. **step 1（列出債券期別）**：`firstin` 的值是 **`ture`**（拼錯的，故意的，不能改）
   ```
   POST ajax_t47sb18 或 ajax_t47sb07
   encodeURIComponent=1, step=1, firstin=ture, off=1,
   queryName=co_id, inpuType=co_id, TYPEK=all, co_id=<公司代號>
   ```
2. **step 2（明細）**：`firstin` 拼回正確的 **`true`**；參數名每頁不同：
   - `t47sb18`（月報）：`ab=ym0, bond_yrn=<期別>, bond_subn=$M00000002, ym0=<民國年月5碼 如11506>`（蛇形命名、民國年）
   - `t47sb07`（基本資料）：`bondKind=5, bondYrn=<期別>, bondSubn=$M00000002, monyrReg=<西元年月6碼 如202606>`（駝峰命名、西元年）
   - `bond_subn` 內部編號從 step 1 回應的 onclick 屬性解析
3. **頻率限制**：每請求間隔 ≥3 秒，否則暫時封 IP
4. Headers 需帶 UA 與 `Referer: https://mopsov.twse.com.tw/mops/web/<功能代號>`
5. Python 3.13 對台灣機構憑證會報 `Missing Subject Key Identifier` → 一律 `verify=False` ＋ `urllib3.disable_warnings()`
6. 新版 MOPS（mops.twse.com.tw）把參數加密成 `parameters=<hash>`，不可程式化；一律打舊版 mopsov 的 ajax_ 端點

### 3.4 DevTools 抓包 SOP（未來挖新端點用）

1. 開目標查詢頁 → `F12`（Windows）或 `Cmd+Option+I`（Mac）→ 網路(Network)分頁
2. 勾「**保留記錄**」（防跳轉清空）→ 點 **Fetch/XHR** → 按 **🚫 清空**
3. 條件填在**網頁表單**上（不是 DevTools 篩選框！）→ 按查詢
4. 點清單新跳出的請求 → Headers 的 **Request URL** ＋ **Payload** 內容
5. 若參數不明，改抓頁面原始表單：GET 該頁 → regex 印出 `<input>/<select>/onclick`，onclick 裡通常寫著 step 2 的完整參數配方

---

## 4. Token 與憑證管理

| Token | 用途 | 期限 | 存放位置 |
|---|---|---|---|
| FinMind API token | stock-viewer 抓股價 | **永久**（2026-07 起 FinMind 後台提供永久 token；舊 token 於 2026-07-13 到期已淘汰） | 本機各 script ＋ stock-viewer repo 的 Actions Secret |
| GitHub PAT (classic) | git push | 永不過期 | macOS 鑰匙圈（credential-osxkeychain） |

FinMind 後台：finmindtrade.com → 登入 → User → api token 金鑰。免費帳號限 **600 次/小時**。

---

## 5. 故障排除

| 症狀 | 原因 | 解法 |
|---|---|---|
| 新聞/儀表板一直是舊的 | 開到本機舊檔或瀏覽器快取 | 確認網址是 `github.io` 開頭；`Cmd+Shift+R` 強制重整；無痕視窗驗證 |
| `git push` 被 rejected | Actions bot 已推新 commit，本機分岔 | `cb_openapi.db` 是二進位不能自動合併：先 `cp` 備份本機 db → `git pull --no-rebase` → `git checkout --theirs cb_openapi.db` → 用 ATTACH DATABASE 把本機新表灌回 → 重新 generate → push |
| Actions 紅叉 | 看 log 的紅字步驟 | MOPS 對海外 IP 不穩時，`update_conv_weekly` 可改本機跑：`python fetch_conv_prices.py --stale-days 7` 後 push |
| MOPS 回空殼頁（len≈2500） | 參數名/值錯誤 | 對照 3.3；記住 ture/true 與民國/西元陷阱 |
| requests SSL 憑證錯誤 | Python 3.13 嚴格檢查 | `verify=False` |
| 快照「查無」的代碼（YB48AA、N/A…） | 海外 ECB 或雜訊列 | 正常，忽略 |
| 60 天沒 commit 排程被 GitHub 暫停 | repo 無活動 | 三個 repo 每日自動 commit，不會觸發；僅備查 |
| FinMind 401/402 | token 錯或超量 | 後台確認 token；每小時 600 次上限 |

---

## 6. 待辦 / 未來擴充

- [ ] **歷史餘額回填**：用 `ajax_t47sb18`（單檔單月）批次回抓，重建已到期 CB 的逐月餘額與轉換張數流量（端點已打通，自動化未建）
- [ ] 變動偵測輸出接入 email 日報（cb_snapshot_ingest 的輸出已結構化，易改 HTML）
- [ ] 溢價率欄位：需接股價（可用 stock-viewer 的 FinMind 資料交叉）
- [ ] CBAS 承作餘額 OpenAPI 接入
- [ ] `cb_openapi.db` 若數年後 repo 過肥 → 改按月 CSV 分檔

---

## 7. 大事記

- **2026-06**：TPEx 網站改版，舊版端點全滅；本機四套 CB 系統並存（詳見 `~/cb-monitor` 的 CLAUDE.md）
- **2026-07-07**：cb-monitor-cloud 上雲，本機 launchd 停用；cb-monitor 新 repo 建立，bond_ISSBD5 每日快照上線
- **2026-07-09**：破解 MOPS t47sb18／t47sb07 兩段式參數；於舊程式 `fill_missing_conv.py` 中重新發現 t120sg06 轉換價端點；匯入既有 1,137 筆轉換價歷史
- **2026-07-10**：轉換價格欄位上線（1,173 筆入庫，含即將重設標記）
- **2026-07-11**：FinMind 永久 token 換裝；cb_news「失效」確認為開到本機舊檔的誤會
