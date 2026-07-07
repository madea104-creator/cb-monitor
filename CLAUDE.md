# cb-monitor

## 這是什麼
台灣可轉債(CB)監控 — 抓 TPEx OpenAPI 每日快照存歷史，產生靜態儀表板，由 GitHub Actions 排程。
純本機、輕量版，跟 ~/Project/cb_monitor（launchd + email 版本，功能更完整）是完全不同的兩套系統，
不要混淆或假設兩邊資料互通。

## 資料流程
TPEx OpenAPI (bond_ISSBD5) → cb_snapshot_ingest.py → cb_openapi.db (cb_snapshot 表)
→ generate_cb_html.py → index.html（純靜態單檔，零外部依賴）

## 規則
- cb_openapi.db 是唯一的 source of truth，主鍵 (bond_code, snapshot_date)；
  同一天重跑要保持冪等（覆蓋而非新增），不要改成 append-only。
- 欄位是從 API 回傳動態建立（sanitize() + ALTER TABLE），API 端若改欄位名，
  ingest 會自動長出新欄位，但 generate_cb_html.py 裡是寫死的 PascalCase 欄位名
  （OutstandingAmount、IssueAmount…），兩邊要保持同步，不要各自改名。
- 排程是 GitHub Actions cron（週一到五 UTC 11:30 = 台灣 19:30），不是本機 launchd；
  cb_openapi.db 和 index.html 由 CI 自動 commit push，本機跑完測試後不要手動 commit 這兩個檔案，
  以免跟 CI 的 commit 衝突。
- 專案刻意保持零依賴（只用 requests + 標準庫），新增功能前先評估是否真的需要加套件。
- index.html 是唯一輸出介面，不要引入前端框架/build step，維持「單檔可直接丟 GitHub Pages」的特性。
- 若要加 email/news alert，ingest 腳本已經在做「新掛牌/下市/餘額變動」偵測，直接接在那段邏輯後面即可，
  不需要重新設計比對機制。

## 相關但獨立的系統
以下系統都跟「CB 監控」這個主題有關，但跟本 repo **沒有程式碼或資料共用關係**，
提到「CB」相關需求時，先確認使用者指的是本 repo 還是下面這些：

1. **`~/Project/cb_monitor`**（launchd 舊系統）
   由 `com.peggy.cb.daily`（週一到五 15:30）與 `com.peggy.cb.weekly`（週一 15:25）觸發，
   功能比本 repo 完整（premium/moneyness 警示、CB 新聞、email 報表），本機 SQLite `cb_monitor.db`，
   不進 git。長期計畫是把這裡的功能逐步搬到本 repo 後，此系統退役、移除 launchd job。

2. **`~/twse_cb_data`**（CB 正股資料）
   由 `com.madea104.twsecb`（週一到五 16:00）觸發 `~/Project/run_twse_fetch.sh` →
   `twse_cb_underlying_fetcher.py`，抓的是 TWSE 全市場當沖/融資融券/成交/評價資料，
   過濾出 CB **標的股（正股）**，寫進 `twse_cb.sqlite`。抓的是正股，不是 CB 本身，跟本 repo 資料不重疊。

3. **`~/money104_data`**（爬蟲已失效，待清理）
   來源是 `~/Project/money104_cb_scraper.py`，想爬 money104 (i-stock/算利教官) 的 CB 資料，
   但目前被 reCAPTCHA 擋掉，資料夾裡只剩失敗時的除錯頁面快照（`debug_daily_denied_*.html`），
   沒有任何實際資料。這條管線目前是死的，待清理/棄用。

4. **stock-viewer repo**（GitHub Actions 雲端備份）
   本機對應目錄 `~/Project/stock-viewer-site`。用 GitHub Actions 做雲端備份，
   依賴 FinMind API token，**token 於 2026-07-13 到期**，屆時需更新 token 否則該 repo 的排程會失敗。
