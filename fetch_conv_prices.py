# -*- coding: utf-8 -*-
"""
fetch_conv_prices.py
抓取/維護「轉換價格歷史」表（來源：MOPS ajax_t120sg06，你舊系統打通的端點）
存入 cb_openapi.db 的 conv_price 表，供 generate_cb_html.py 顯示「目前轉換價」。

三種模式：
  1) 首次匯入既有歷史（強烈建議先做，一秒完成、不打 MOPS）：
       python fetch_conv_prices.py --seed 可轉債_轉換價歷史_全部.csv
  2) 平常增量（預設）：只抓「快照裡有、但 conv_price 還沒有」的 CB：
       python fetch_conv_prices.py
  3) 定期刷新：連同太久沒更新的一起抓（建議每週）：
       python fetch_conv_prices.py --stale-days 7

註：MOPS 對頻率敏感，每檔間隔 3 秒；387 檔全抓約 20 分鐘，增量通常只有幾檔。
"""

import argparse
import datetime as dt
import io
import re
import sqlite3
import time

import pandas as pd
import requests
import urllib3

urllib3.disable_warnings()

URL = "https://mopsov.twse.com.tw/mops/web/ajax_t120sg06"
SLEEP = 3.0

S = requests.Session()
S.verify = False
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://mopsov.twse.com.tw/mops/web/t120sb02",
})


def roc_to_iso(s):
    """'115/07/22' → '2026-07-22'；解析失敗回 None。範圍值取第一個日期。"""
    if s is None:
        return None
    m = re.search(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", str(s))
    if not m:
        return None
    y, mo, d = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conv_price (
            bond_code   TEXT NOT NULL,
            reset_date  TEXT NOT NULL,   -- ISO 格式
            price       REAL,
            shares      REAL,
            kind        TEXT,            -- 掛牌 / 反稀釋 / ...
            reset_pct   TEXT,
            cum_pct     TEXT,
            fetched_at  TEXT,
            PRIMARY KEY (bond_code, reset_date, price)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conv_meta (
            bond_code  TEXT PRIMARY KEY,
            fetched_at TEXT,
            status     TEXT             -- ok / empty / error
        )
    """)


def upsert_rows(conn, bond_code, df, fetched_at):
    """df 欄位：代碼 簡稱 類型 轉(交)換價格 轉(交)換股數 重設日期(起迄日期) 重設幅度% 累積重設幅度%"""
    n = 0
    cols = {c: str(c) for c in df.columns}
    def col(*keys):
        for c in df.columns:
            if any(k in str(c) for k in keys):
                return c
        return None
    c_price, c_shares = col("價格"), col("股數")
    c_date, c_kind = col("日期"), col("類型")
    c_pct, c_cum = col("重設幅度"), col("累積")
    for _, row in df.iterrows():
        iso = roc_to_iso(row.get(c_date))
        price = pd.to_numeric(row.get(c_price), errors="coerce")
        if iso is None or pd.isna(price):
            continue
        conn.execute(
            "INSERT OR REPLACE INTO conv_price VALUES (?,?,?,?,?,?,?,?)",
            (str(bond_code), iso, float(price),
             float(pd.to_numeric(row.get(c_shares), errors="coerce") or 0),
             str(row.get(c_kind, "")),
             str(row.get(c_pct, "")), str(row.get(c_cum, "")), fetched_at))
        n += 1
    return n


def fetch_one(bond_id: str) -> pd.DataFrame:
    p = {"encodeURIComponent": "1", "firstin": "true", "bond_id": bond_id,
         "step": "1", "data_type": "", "date1": "", "date2": ""}
    r = S.get(URL, params=p, timeout=30)
    r.encoding = r.apparent_encoding or "utf-8"
    if "查無" in r.text:
        return pd.DataFrame()
    try:
        tabs = pd.read_html(io.StringIO(r.text))
    except ValueError:
        return pd.DataFrame()
    tabs = [t for t in tabs if t.shape[0] > 0 and t.shape[1] >= 3]
    if not tabs:
        return pd.DataFrame()
    return max(tabs, key=lambda t: t.shape[0] * t.shape[1])


def seed_csv(conn, path):
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    now = dt.datetime.now().isoformat(timespec="seconds")
    total = 0
    key = "可轉債代碼" if "可轉債代碼" in df.columns else "代碼"
    for code, g in df.groupby(key):
        total += upsert_rows(conn, code, g, now)
        conn.execute("INSERT OR REPLACE INTO conv_meta VALUES (?,?,?)",
                     (str(code), now, "ok"))
    conn.commit()
    print(f"已匯入 {path}：{total} 筆轉換價歷史，涵蓋 {df[key].nunique()} 檔 CB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="cb_openapi.db")
    ap.add_argument("--seed", help="匯入既有歷史 CSV（不打 MOPS）")
    ap.add_argument("--stale-days", type=int, default=None,
                    help="連同超過 N 天未更新的 CB 一起重抓")
    ap.add_argument("--all", action="store_true", help="全部重抓（慎用，約20分鐘）")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    ensure_table(conn)

    if args.seed:
        seed_csv(conn, args.seed)
        return

    # 目標清單：最新快照的所有 CB
    latest = conn.execute("SELECT MAX(snapshot_date) FROM cb_snapshot").fetchone()[0]
    if not latest:
        print("cb_snapshot 沒資料，請先跑 cb_snapshot_ingest.py")
        return
    codes = [r[0] for r in conn.execute(
        "SELECT bond_code FROM cb_snapshot WHERE snapshot_date=? ORDER BY bond_code", (latest,))]

    meta = dict(conn.execute("SELECT bond_code, fetched_at FROM conv_meta"))
    todo = []
    cutoff = None
    if args.stale_days is not None:
        cutoff = (dt.datetime.now() - dt.timedelta(days=args.stale_days)).isoformat()
    for c in codes:
        if args.all or c not in meta or (cutoff and (meta[c] or "") < cutoff):
            todo.append(c)

    print(f"快照共 {len(codes)} 檔，需抓取 {len(todo)} 檔"
          f"（預估 {len(todo)*SLEEP/60:.0f} 分鐘）")
    ok = empty = err = 0
    for i, code in enumerate(todo, 1):
        now = dt.datetime.now().isoformat(timespec="seconds")
        try:
            df = fetch_one(code)
            if df.empty:
                status, empty = "empty", empty + 1
                print(f"  ({i}/{len(todo)}) {code} — 查無")
            else:
                n = upsert_rows(conn, code, df, now)
                status, ok = "ok", ok + 1
                print(f"  ({i}/{len(todo)}) {code} ✓ {n} 筆")
        except Exception as ex:
            status, err = "error", err + 1
            print(f"  ({i}/{len(todo)}) {code} ✗ {str(ex)[:60]}")
        conn.execute("INSERT OR REPLACE INTO conv_meta VALUES (?,?,?)", (code, now, status))
        conn.commit()
        time.sleep(SLEEP)

    print(f"\n完成：成功 {ok}、查無 {empty}、失敗 {err}")
    total = conn.execute("SELECT COUNT(*) FROM conv_price").fetchone()[0]
    print(f"conv_price 表目前共 {total} 筆歷史紀錄")
    conn.close()


if __name__ == "__main__":
    main()
