# -*- coding: utf-8 -*-
"""
cb_snapshot_ingest.py
每日抓取 TPEx OpenAPI「轉(交)換公司債基本資料」(bond_ISSBD5) 存入 SQLite，
自行累積餘額 / 賣回日等欄位的歷史時間序列。

特性：
  * 獨立資料庫檔（預設 cb_openapi.db），完全不碰既有系統
  * 欄位動態建表：API 若增減欄位，自動 ALTER TABLE 補上，不會掛掉
  * 以 (bond_code, snapshot_date) 為主鍵，重跑同一天冪等（覆蓋不重複）
  * 每次執行自動比對前一次快照，印出「餘額變動」與「新掛牌 CB」清單
    （之後要接你的 email 報表或 CB news alert 很方便）

用法：
  pip install requests
  python cb_snapshot_ingest.py                 # 抓今日快照
  python cb_snapshot_ingest.py --db /path/to/cb_openapi.db

排程（穩定後再掛）：
  launchd 每日 18:00 後執行一次即可（TPEx 傍晚更新）
"""

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys

import requests

API_URL = "https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data"
HEADERS = {
    "accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}
TABLE = "cb_snapshot"


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def sanitize(col: str) -> str:
    """把 API 欄位名轉成安全的 SQLite 欄位名"""
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", col).strip("_")
    return s or "col"


def find_key(keys, *patterns):
    """在 API 欄位名中尋找符合關鍵字的欄位（不分大小寫）"""
    for p in patterns:
        for k in keys:
            if p.lower() in k.lower():
                return k
    return None


def num(v):
    """字串轉數字（去逗號），失敗回 None"""
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def fetch_api() -> list[dict]:
    r = requests.get(API_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"API 回傳異常：{str(data)[:200]}")
    return data


def ensure_table(conn: sqlite3.Connection, columns: list[str]):
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            bond_code     TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            fetched_at    TEXT NOT NULL,
            PRIMARY KEY (bond_code, snapshot_date)
        )
    """)
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})")}
    for c in columns:
        if c not in existing:
            conn.execute(f'ALTER TABLE {TABLE} ADD COLUMN "{c}" TEXT')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="cb_openapi.db", help="SQLite 檔案路徑")
    args = ap.parse_args()

    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] 抓取 {API_URL}")
    rows = fetch_api()
    keys = list(dict.fromkeys(k for row in rows for k in row.keys()))
    print(f"取得 {len(rows)} 檔 CB，欄位：{keys}")

    # 自動辨識關鍵欄位（API 欄位名以實際回傳為準）
    k_code = find_key(keys, "bondcode", "securitycode", "code")
    k_name = find_key(keys, "shortname", "bondname", "name")
    k_date = find_key(keys, "date")
    k_outstanding = find_key(keys, "outstandingamount", "outstanding")
    if not k_code:
        print("[!] 找不到債券代碼欄位，請把上面印出的欄位清單貼給 Claude 調整", file=sys.stderr)
        sys.exit(1)

    snapshot_date = (str(rows[0].get(k_date)) if k_date and rows[0].get(k_date)
                     else dt.date.today().strftime("%Y%m%d"))
    fetched_at = dt.datetime.now().isoformat(timespec="seconds")
    col_map = {k: sanitize(k) for k in keys}

    conn = sqlite3.connect(args.db)
    try:
        ensure_table(conn, list(col_map.values()))

        # --- 讀取「前一次快照」供比對 ---
        prev = {}
        prev_date = conn.execute(
            f"SELECT MAX(snapshot_date) FROM {TABLE} WHERE snapshot_date < ?",
            (snapshot_date,),
        ).fetchone()[0]
        if prev_date and k_outstanding:
            oc = col_map[k_outstanding]
            for code, out_amt in conn.execute(
                f'SELECT bond_code, "{oc}" FROM {TABLE} WHERE snapshot_date = ?',
                (prev_date,),
            ):
                prev[code] = out_amt

        # --- 寫入本次快照 ---
        cols = ["bond_code", "snapshot_date", "fetched_at"] + list(col_map.values())
        placeholders = ",".join("?" for _ in cols)
        colnames = ",".join(f'"{c}"' for c in cols)
        sql = f"INSERT OR REPLACE INTO {TABLE} ({colnames}) VALUES ({placeholders})"
        for row in rows:
            values = [str(row.get(k_code)), snapshot_date, fetched_at]
            values += [None if row.get(k) is None else str(row.get(k)) for k in keys]
            conn.execute(sql, values)
        conn.commit()
        print(f"已寫入快照 snapshot_date={snapshot_date} → {args.db}")

        # --- 變動偵測 ---
        if prev:
            cur = {str(r.get(k_code)): r for r in rows}
            new_bonds = sorted(set(cur) - set(prev))
            gone_bonds = sorted(set(prev) - set(cur))
            changed = []
            if k_outstanding:
                for code in set(cur) & set(prev):
                    a, b = num(prev[code]), num(cur[code].get(k_outstanding))
                    if a is not None and b is not None and a != b:
                        nm = cur[code].get(k_name, "") if k_name else ""
                        changed.append((code, nm, a, b))

            print(f"\n=== 與上次快照({prev_date})比對 ===")
            if new_bonds:
                print(f"新掛牌 CB: {new_bonds}")
            if gone_bonds:
                print(f"消失(到期/下市) CB: {gone_bonds}")
            if changed:
                print("餘額變動：")
                for code, nm, a, b in sorted(changed, key=lambda x: x[3] - x[2]):
                    print(f"  {code} {nm}: {a:,.0f} → {b:,.0f} ({b - a:+,.0f})")
            if not (new_bonds or gone_bonds or changed):
                print("無變動")
        else:
            print("\n（首次執行，尚無前次快照可比對）")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
