# -*- coding: utf-8 -*-
"""
generate_cb_html.py
讀取 cb_openapi.db（cb_snapshot_ingest.py 累積的每日快照），
產生單檔 HTML 儀表板 cb_dashboard.html。

特色：
  * 餘額消化率量條（1 - 餘額/發行額）— 掃描強勢 CB
  * 與前一次快照的餘額變動（Δ）自動標示
  * 搜尋（代碼/簡稱/發行人）、快速篩選、多欄排序
  * 點列展開：該檔 CB 的逐日餘額歷史（隨快照累積增長）
  * 純單檔、零外部依賴，可直接丟 GitHub Pages

用法：
  python generate_cb_html.py
  python generate_cb_html.py --db cb_openapi.db --out cb_dashboard.html
"""

import argparse
import datetime as dt
import json
import sqlite3


def num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fmt_date(s):
    """20260706 → 2026/07/06；其他格式原樣返回"""
    s = str(s or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}/{s[4:6]}/{s[6:]}"
    return s


def load(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT snapshot_date FROM cb_snapshot ORDER BY snapshot_date")]
    if not dates:
        raise SystemExit("資料庫沒有快照，請先跑 cb_snapshot_ingest.py")
    latest, prev = dates[-1], (dates[-2] if len(dates) > 1 else None)

    rows = conn.execute(
        "SELECT * FROM cb_snapshot WHERE snapshot_date = ?", (latest,)).fetchall()

    prev_out = {}
    if prev:
        for r in conn.execute(
            "SELECT bond_code, OutstandingAmount FROM cb_snapshot WHERE snapshot_date = ?",
            (prev,),
        ):
            prev_out[r[0]] = num(r[1])

    # 每檔的餘額歷史（全部快照）
    hist = {}
    for r in conn.execute(
        "SELECT bond_code, snapshot_date, OutstandingAmount FROM cb_snapshot ORDER BY snapshot_date"
    ):
        hist.setdefault(r[0], []).append([fmt_date(r[1]), num(r[2])])

    bonds = []
    for r in rows:
        code = r["bond_code"]
        issue, out = num(r["IssueAmount"]), num(r["OutstandingAmount"])
        digest = (1 - out / issue) if (issue and out is not None and issue > 0) else None
        p = prev_out.get(code)
        delta = (out - p) if (out is not None and p is not None) else None
        bonds.append({
            "code": code,
            "name": r["ShortName"] or "",
            "issuer": r["IssuerName"] or "",
            "issue": issue,
            "out": out,
            "digest": round(digest * 100, 1) if digest is not None else None,
            "delta": delta,
            "put_date": fmt_date(r["PutOptionDate"]),
            "put_price": num(r["PutOptionPrice"]),
            "maturity": fmt_date(r["MaturityDate"]),
            "listing": fmt_date(r["ListingDate"]),
            "conv_price": num(r["Conversion_ExchangePriceAtIssuance"]),
            "chg_date": fmt_date(r["OutstandingChangeDate"]),
            "chg_desc": r["OutstandingChangeDescription"] or "",
            "underwriter": r["Underwriter"] or "",
            "hist": hist.get(code, []),
        })
    conn.close()
    return bonds, fmt_date(latest), fmt_date(prev) if prev else None


HTML = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>可轉債快照 __LATEST__</title>
<style>
:root{
  --paper:#F2F4F7; --card:#FFFFFF; --ink:#17283B; --ink2:#5B6B7D;
  --line:#DDE3EA; --tpex:#1D56A5; --up:#C8382E; --dn:#1E7F4F;
  --gauge:#1D56A5; --gauge-bg:#E4EAF1; --chip:#EDF1F6;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);
  font-family:"Helvetica Neue","PingFang TC","Microsoft JhengHei",sans-serif;
  font-size:14px;line-height:1.45}
.num{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-variant-numeric:tabular-nums}

/* ── 報頭 ── */
header{background:var(--card);border-bottom:3px double var(--tpex);padding:20px 24px 14px}
.mast{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 18px;max-width:1200px;margin:0 auto}
.mast h1{font-family:"Noto Serif TC","PMingLiU",serif;font-size:24px;font-weight:700;
  letter-spacing:.14em;color:var(--tpex)}
.mast .snap{color:var(--ink2);font-size:13px}
.mast .stats{margin-left:auto;display:flex;gap:18px;font-size:13px;color:var(--ink2)}
.mast .stats b{color:var(--ink);font-size:16px}

/* ── 工具列 ── */
.toolbar{max-width:1200px;margin:14px auto 0;padding:0 24px;
  display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.toolbar input{flex:1;min-width:180px;padding:8px 12px;border:1px solid var(--line);
  border-radius:6px;font-size:14px;background:var(--card)}
.toolbar input:focus{outline:2px solid var(--tpex);outline-offset:-1px}
.chipbar{display:flex;gap:6px;flex-wrap:wrap}
.chip{padding:7px 12px;border:1px solid var(--line);border-radius:999px;background:var(--chip);
  font-size:13px;cursor:pointer;color:var(--ink2)}
.chip.on{background:var(--tpex);border-color:var(--tpex);color:#fff}
.chip:focus-visible{outline:2px solid var(--tpex);outline-offset:2px}

/* ── 表格 ── */
.wrap{max-width:1200px;margin:12px auto 60px;padding:0 24px}
.tablecard{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:auto;max-height:calc(100vh - 215px)}
table{width:100%;border-collapse:collapse;min-width:980px}
thead th{position:sticky;top:0;z-index:2;background:var(--card);border-bottom:2px solid var(--ink);
  padding:10px 10px;text-align:right;font-size:12.5px;color:var(--ink2);
  white-space:nowrap;cursor:pointer;user-select:none}
thead th:first-child,thead th:nth-child(2){text-align:left}
thead th .arr{color:var(--tpex)}
tbody td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
tbody td:first-child,tbody td:nth-child(2){text-align:left}
tbody tr.row{cursor:pointer}
tbody tr.row:hover{background:#F6F9FC}
.codecell b{color:var(--tpex)}
.codecell span{color:var(--ink2);font-size:12px;margin-left:6px}

/* 消化率量條 —— 招牌元素 */
.gauge{display:inline-flex;align-items:center;gap:8px;justify-content:flex-end;width:150px}
.gauge .bar{flex:1;height:8px;border-radius:4px;background:var(--gauge-bg);overflow:hidden}
.gauge .bar i{display:block;height:100%;background:var(--gauge)}
.gauge .pct{width:48px;font-size:12.5px}
.d-up{color:var(--up)} .d-dn{color:var(--dn)} .muted{color:var(--ink2)}
.putsoon{color:var(--up);font-weight:600}

/* 展開明細 */
tr.detail td{background:#F8FAFC;padding:14px 18px;text-align:left}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:6px 22px;
  font-size:13px;margin-bottom:10px}
.dgrid span{color:var(--ink2)}
.htable{border-collapse:collapse;min-width:0}
.htable th,.htable td{border:1px solid var(--line);padding:4px 10px;font-size:12.5px;text-align:right}
.htable th{background:var(--chip);color:var(--ink2);font-weight:500}
.empty{padding:40px;text-align:center;color:var(--ink2)}
footer{max-width:1200px;margin:0 auto 40px;padding:0 24px;font-size:12px;color:var(--ink2)}
@media (max-width:640px){
  header{padding:14px 14px 10px}.mast h1{font-size:19px}
  .toolbar,.wrap,footer{padding:0 10px}.mast .stats{width:100%;margin-left:0}
}
@media (prefers-reduced-motion:no-preference){
  .gauge .bar i{transition:width .4s ease}
}
</style>
</head>
<body>
<header>
  <div class="mast">
    <h1>可轉債快照</h1>
    <div class="snap">快照日 __LATEST__ __PREVNOTE__ ・ 資料：櫃買中心 OpenAPI</div>
    <div class="stats">
      <div>掛牌 <b id="stTotal">–</b> 檔</div>
      <div>本次變動 <b id="stChanged">–</b> 檔</div>
      <div>顯示中 <b id="stShown">–</b> 檔</div>
    </div>
  </div>
</header>

<div class="toolbar">
  <input id="q" type="search" placeholder="搜尋代碼、簡稱或發行人…" aria-label="搜尋">
  <div class="chipbar" id="chips" role="group" aria-label="快速篩選">
    <button class="chip on" data-f="all">全部</button>
    <button class="chip" data-f="changed">本次有變動</button>
    <button class="chip" data-f="hot">消化率 &gt; 80%</button>
    <button class="chip" data-f="putsoon">賣回日 180 天內</button>
  </div>
</div>

<div class="wrap">
  <div class="tablecard">
    <table aria-label="可轉債清單">
      <thead><tr>
        <th data-s="code">代碼／簡稱</th>
        <th data-s="issuer">發行人</th>
        <th data-s="issue">發行額</th>
        <th data-s="out">餘額</th>
        <th data-s="delta">Δ餘額</th>
        <th data-s="digest">消化率</th>
        <th data-s="conv_price">發行轉換價</th>
        <th data-s="put_date">賣回日</th>
        <th data-s="maturity">到期日</th>
      </tr></thead>
      <tbody id="tb"></tbody>
    </table>
    <div class="empty" id="empty" hidden>沒有符合條件的 CB — 換個關鍵字或篩選看看</div>
  </div>
</div>

<footer>消化率 = 1 − 餘額 ÷ 發行額。Δ餘額為與前一次快照之比較；每日執行 cb_snapshot_ingest.py 後重新產生本頁即可累積歷史。</footer>

<script>
const DATA = __DATA__;
const today = new Date("__TODAY__");
const fmtA = v => v==null ? "–" : (v/1e8).toFixed(2)+" 億";
const fmtD = v => v==null ? "–" : (v>0?"+":"−")+(Math.abs(v)/1e6).toFixed(1)+" 百萬";
const putDays = s => { if(!s) return null;
  const d=new Date(s.replaceAll("/","-")); return isNaN(d)?null:Math.round((d-today)/864e5); };

let filter="all", query="", sortKey="digest", sortAsc=false, openCode=null;

const tb=document.getElementById("tb");
function rows(){
  let r=DATA.filter(b=>{
    if(query){ const q=query.toLowerCase();
      if(!(b.code.includes(q)||b.name.toLowerCase().includes(q)||b.issuer.toLowerCase().includes(q))) return false; }
    if(filter==="changed") return b.delta!=null && b.delta!==0;
    if(filter==="hot")     return b.digest!=null && b.digest>80;
    if(filter==="putsoon"){ const d=putDays(b.put_date); return d!=null && d>=0 && d<=180; }
    return true;
  });
  r.sort((a,b)=>{
    let x=a[sortKey], y=b[sortKey];
    if(x==null) return 1; if(y==null) return -1;
    if(typeof x==="string"){ x=x||"\uffff"; y=y||"\uffff";
      return sortAsc ? x.localeCompare(y) : y.localeCompare(x); }
    return sortAsc ? x-y : y-x;
  });
  return r;
}
function gauge(p){ if(p==null) return "–";
  return `<span class="gauge"><span class="bar"><i style="width:${Math.min(100,Math.max(0,p))}%"></i></span><span class="pct num">${p.toFixed(1)}%</span></span>`; }

function render(){
  const list=rows();
  document.getElementById("stShown").textContent=list.length;
  document.getElementById("empty").hidden=list.length>0;
  tb.innerHTML=list.map(b=>{
    const d=putDays(b.put_date);
    const putCls=(d!=null&&d>=0&&d<=180)?"putsoon":"";
    const deltaCls=b.delta==null?"muted":(b.delta<0?"d-up":"d-dn");
    const open=openCode===b.code;
    let html=`<tr class="row" data-code="${b.code}" aria-expanded="${open}">
      <td class="codecell"><b class="num">${b.code}</b> ${b.name}</td>
      <td>${b.issuer}</td>
      <td class="num">${fmtA(b.issue)}</td>
      <td class="num">${fmtA(b.out)}</td>
      <td class="num ${deltaCls}">${b.delta==null?"–":fmtD(b.delta)}</td>
      <td>${gauge(b.digest)}</td>
      <td class="num">${b.conv_price==null?"–":b.conv_price.toFixed(2)}</td>
      <td class="num ${putCls}">${b.put_date||"–"}${d!=null&&d>=0?`<span class="muted"> (${d}天)</span>`:""}</td>
      <td class="num">${b.maturity||"–"}</td></tr>`;
    if(open){
      const h=b.hist.map(x=>`<tr><td class="num">${x[0]}</td><td class="num">${x[1]==null?"–":x[1].toLocaleString()}</td></tr>`).join("");
      html+=`<tr class="detail"><td colspan="9">
        <div class="dgrid">
          <div><span>賣回價</span> <span class="num" style="color:var(--ink)">${b.put_price==null?"–":b.put_price.toFixed(2)}</span></div>
          <div><span>掛牌日</span> ${b.listing||"–"}</div>
          <div><span>承銷商</span> ${b.underwriter||"–"}</div>
          <div><span>餘額最後變動</span> ${b.chg_date||"–"} ${b.chg_desc}</div>
        </div>
        <table class="htable"><thead><tr><th>快照日</th><th>餘額 (元)</th></tr></thead><tbody>${h}</tbody></table>
      </td></tr>`;
    }
    return html;
  }).join("");
}

tb.addEventListener("click",e=>{
  const tr=e.target.closest("tr.row"); if(!tr) return;
  openCode = openCode===tr.dataset.code ? null : tr.dataset.code; render();
});
document.getElementById("q").addEventListener("input",e=>{query=e.target.value.trim();render();});
document.getElementById("chips").addEventListener("click",e=>{
  const c=e.target.closest(".chip"); if(!c) return;
  document.querySelectorAll(".chip").forEach(x=>x.classList.toggle("on",x===c));
  filter=c.dataset.f; render();
});
document.querySelectorAll("thead th").forEach(th=>{
  th.addEventListener("click",()=>{
    const k=th.dataset.s;
    if(sortKey===k) sortAsc=!sortAsc; else {sortKey=k; sortAsc=(k==="code"||k==="issuer"||k==="put_date"||k==="maturity");}
    document.querySelectorAll("thead th .arr").forEach(a=>a.remove());
    th.insertAdjacentHTML("beforeend",`<span class="arr">${sortAsc?" ▲":" ▼"}</span>`);
    render();
  });
});

document.getElementById("stTotal").textContent=DATA.length;
document.getElementById("stChanged").textContent=DATA.filter(b=>b.delta!=null&&b.delta!==0).length;
render();
</script>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="cb_openapi.db")
    ap.add_argument("--out", default="cb_dashboard.html")
    args = ap.parse_args()

    bonds, latest, prev = load(args.db)
    prevnote = f"（比較基準 {prev}）" if prev else "（尚無前次快照可比較）"
    html = (HTML
            .replace("__DATA__", json.dumps(bonds, ensure_ascii=False))
            .replace("__LATEST__", latest)
            .replace("__PREVNOTE__", prevnote)
            .replace("__TODAY__", dt.date.today().isoformat()))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"完成：{args.out}（{len(bonds)} 檔，快照日 {latest}）")


if __name__ == "__main__":
    main()
