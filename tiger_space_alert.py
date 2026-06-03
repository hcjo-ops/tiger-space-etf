#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TIGER 미국우주테크(0183J0) 일일 Gmail 알림.

매일 미국장 마감 후(한국 오전) 실행하면:
  1) 네이버 PDP에서 구성종목·주식수를 가져와 비중을 자동 계산
  2) 종목 전일 미국 종가/등락률 + 원/달러 환율 변동 수집
  3) 오늘자 한국 ETF의 예상 변동폭을 NAV 기준으로 추정
  4) 종목별 주요 뉴스를 수집·선별하고 한국어로 번역·요약
  5) Gmail로 본인에게 메일 발송 (HTML)

⚠️ 예상 변동폭은 직전 미국 종가·환율 기반 단순 추정치입니다. 장중 미국 선물·환율·
   괴리율에 따라 실제 시초가/종가는 달라집니다. 투자 자문이 아니며 참고용입니다.

환경변수:
  GMAIL_ADDRESS       발송 Gmail 주소
  GMAIL_APP_PASSWORD  Gmail 앱 비밀번호(2단계인증 후 발급, 16자리)
  MAIL_TO             받는 주소(생략 시 GMAIL_ADDRESS = 나에게)

사용법:
  python tiger_space_alert.py            # 수집 + 메일 발송
  python tiger_space_alert.py --no-send  # 발송 없이 콘솔 출력(테스트)
"""

import os
import sys
import json
import time
import smtplib
import datetime as dt
import urllib.parse
import urllib.request
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yfinance as yf

try:
    from deep_translator import GoogleTranslator
    _TRANSLATOR = GoogleTranslator(source="auto", target="ko")
except Exception:
    _TRANSLATOR = None

HERE = os.path.dirname(os.path.abspath(__file__))
HOLDINGS_PATH = os.path.join(HERE, "holdings.json")
ETF_URL = "https://m.stock.naver.com/domestic/stock/0183J0/total"

KEYWORDS = {
    "earnings": 3, "guidance": 3, "revenue": 2, "loss": 2, "profit": 2,
    "contract": 3, "award": 3, "deal": 2, "order": 2,
    "launch": 2, "mission": 2, "satellite": 1,
    "upgrade": 3, "downgrade": 3, "price target": 2, "rating": 2,
    "offering": 3, "dilution": 3, "raise": 1, "bankrupt": 4,
    "sec": 2, "lawsuit": 2, "investigation": 3, "fraud": 4,
    "acquire": 3, "acquisition": 3, "merger": 3, "partnership": 2,
    "ceo": 2, "resign": 3, "fda": 2, "nasa": 2, "pentagon": 2, "defense": 1,
    "surge": 2, "plunge": 3, "soar": 2, "crash": 3, "halt": 3, "beat": 2, "miss": 3,
}


# --------------------------- 구성종목(PDP) ---------------------------

def load_config():
    with open(HOLDINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_basket(cfg):
    """네이버 PDP에서 [{ticker,name,shares}] 수집. 실패 시 fallback_basket 사용."""
    code = cfg.get("naver_code", "0183J0")
    name_map = {k.upper(): v for k, v in cfg["name_to_ticker"].items()}
    url = f"https://m.stock.naver.com/api/stock/{code}/etfAnalysis"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Referer": "https://m.stock.naver.com/"})
        j = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        basket = []
        for a in j.get("etfTop10MajorConstituentAssets", []):
            nm = (a.get("itemName") or "").strip().upper()
            tk = name_map.get(nm)
            shares = float(str(a.get("stockCount", "0")).replace(",", "") or 0)
            if tk and shares > 0:
                basket.append({"ticker": tk, "name": a["itemName"].title(), "shares": shares})
        if len(basket) >= 5:
            return basket, "naver"
    except Exception as e:
        print("네이버 PDP 조회 실패:", e)
    fb = [dict(x) for x in cfg["fallback_basket"]]
    return fb, "fallback"


def fetch_prices(tickers):
    syms = list(dict.fromkeys(tickers)) + ["KRW=X"]
    df = yf.download(syms, period="10d", progress=False, auto_adjust=False)["Close"]
    out = {}
    for sym in syms:
        s = df[sym].dropna() if sym in df else None
        if s is None or len(s) < 2:
            out[sym] = None
            continue
        last, prev = float(s.iloc[-1]), float(s.iloc[-2])
        pct = (last - prev) / prev * 100.0 if prev else 0.0
        out[sym] = {"last": last, "prev": prev, "pct": pct, "date": s.index[-1].date()}
    return out


def compute_expected(basket, prices):
    """NAV 기준: 예상 변동률 ≈ (Σshares·종가 변화)/NAV_prev + 환율 변동률"""
    nav_last = nav_prev = 0.0
    rows = []
    for h in basket:
        p = prices.get(h["ticker"])
        if not p:
            rows.append({**h, "pct": None, "weight": None})
            continue
        nav_last += h["shares"] * p["last"]
        nav_prev += h["shares"] * p["prev"]
        rows.append({**h, "pct": p["pct"], "mv": h["shares"] * p["last"]})
    for r in rows:
        if r.get("mv") is not None and nav_last:
            r["weight"] = r["mv"] / nav_last * 100.0
    stock_ret = (nav_last - nav_prev) / nav_prev * 100.0 if nav_prev else 0.0
    fx = prices.get("KRW=X")
    fx_ret = fx["pct"] if fx else 0.0
    expected = stock_ret + fx_ret
    asof = ""
    for h in basket:
        p = prices.get(h["ticker"])
        if p:
            asof = str(p["date"]); break
    rows.sort(key=lambda r: (r.get("weight") or 0), reverse=True)
    return {"expected": expected, "stock": stock_ret, "fx": fx_ret,
            "rows": rows, "asof": asof}


# --------------------------- 뉴스 ---------------------------

def fetch_news(ticker, name, max_items=6):
    q = urllib.parse.quote(f'"{name}" OR {ticker} stock')
    url = f"https://news.google.com/rss/search?q={q}+when:1d&hl=en-US&gl=US&ceid=US:en"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
    except Exception:
        return []
    out = []
    for it in re.findall(r"<item>(.*?)</item>", raw, re.S)[:max_items]:
        m = re.search(r"<title>(.*?)</title>", it, re.S)
        l = re.search(r"<link>(.*?)</link>", it, re.S)
        src = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
        if not m:
            continue
        out.append({
            "title": re.sub(r"<.*?>", "", m.group(1)).strip(),
            "link": (l.group(1).strip() if l else ""),
            "source": (re.sub(r"<.*?>", "", src.group(1)).strip() if src else ""),
        })
    return out


def score_news(title, move_pct):
    t = title.lower()
    return sum(w for kw, w in KEYWORDS.items() if kw in t) + min(abs(move_pct or 0) / 2.0, 5.0)


def translate(text):
    if not _TRANSLATOR:
        return None
    try:
        return _TRANSLATOR.translate(text[:480])
    except Exception:
        return None


def collect_top_news(rows, top_n=6):
    move = {r["ticker"]: r.get("pct") for r in rows}
    kor = {}  # ticker -> korean name (optional, filled by caller)
    scored, seen = [], set()
    for r in rows:
        for n in fetch_news(r["ticker"], r["name"]):
            key = n["title"][:60]
            if key in seen:
                continue
            seen.add(key)
            s = score_news(n["title"], move.get(r["ticker"]))
            if s <= 0:
                continue
            scored.append((s, r["ticker"], n))
        time.sleep(0.3)
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]
    for _, tk, n in top:  # 번역은 상위 N건만(속도)
        n["title_ko"] = translate(n["title"]) or n["title"]
    return top


# --------------------------- 렌더링 ---------------------------

def fmt_pct(v, nd=2):
    return ("+" if v >= 0 else "") + f"{v:.{nd}f}%"


def render_console(res, top_news, kor):
    L = []
    L.append(f"[TIGER 미국우주테크] {dt.date.today():%m/%d} 예상")
    L.append(f"예상 변동: {fmt_pct(res['expected'])}  (종목 {fmt_pct(res['stock'])} / 환율 {fmt_pct(res['fx'])})")
    L.append(f"기준: 미국 {res['asof']} 종가")
    L.append("─ 구성종목 전일 ─")
    for r in res["rows"]:
        kn = kor.get(r["ticker"], r["name"])
        if r["pct"] is None:
            L.append(f"{r['ticker']} {kn}: N/A")
        else:
            L.append(f"{r['ticker']} {kn}: {fmt_pct(r['pct'],1)} (비중 {r['weight']:.1f}%)")
    L.append("─ 주요 뉴스(한국어) ─")
    for _, tk, n in top_news:
        L.append(f"• [{tk}] {n.get('title_ko', n['title'])} ({n['source']})")
    L.append("※ 추정치·투자자문 아님")
    return "\n".join(L)


def render_html(res, top_news, kor):
    exp = res["expected"]
    color = "#c0392b" if exp >= 0 else "#1e6fd9"  # 한국식: 상승 빨강
    rows_html = ""
    for r in res["rows"]:
        kn = kor.get(r["ticker"], r["name"])
        if r["pct"] is None:
            pct_cell, w_cell = "N/A", "-"
        else:
            pc = "#c0392b" if r["pct"] >= 0 else "#1e6fd9"
            pct_cell = f'<span style="color:{pc};font-weight:600">{fmt_pct(r["pct"],1)}</span>'
            w_cell = f'{r["weight"]:.1f}%'
        rows_html += (f'<tr><td style="padding:6px 10px;border-bottom:1px solid #eee">'
                      f'<b>{r["ticker"]}</b> <span style="color:#666">{kn}</span></td>'
                      f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right">{pct_cell}</td>'
                      f'<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#888">{w_cell}</td></tr>')
    news_html = ""
    for _, tk, n in top_news:
        title_ko = n.get("title_ko", n["title"])
        news_html += (f'<li style="margin:10px 0;line-height:1.5">'
                      f'<a href="{n["link"]}" style="color:#1a4fbf;text-decoration:none;font-weight:600">{title_ko}</a>'
                      f'<div style="color:#999;font-size:12px">[{tk}] {n["source"]} · 원문: {n["title"]}</div></li>')
    return f"""<div style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:640px;margin:auto;color:#222">
  <h2 style="margin:0 0 4px">🚀 TIGER 미국우주테크 — {dt.date.today():%Y/%m/%d}</h2>
  <div style="color:#888;font-size:13px;margin-bottom:14px">기준: 미국 {res['asof']} 종가 · 데이터 yfinance/네이버</div>
  <div style="background:#f7f8fa;border-radius:12px;padding:18px;text-align:center;margin-bottom:18px">
    <div style="font-size:13px;color:#888">오늘 예상 변동폭</div>
    <div style="font-size:34px;font-weight:800;color:{color}">{fmt_pct(exp)}</div>
    <div style="font-size:13px;color:#666">종목 기여 {fmt_pct(res['stock'])} &nbsp;|&nbsp; 환율 {fmt_pct(res['fx'])}</div>
  </div>
  <h3 style="margin:18px 0 6px">구성종목 전일 등락</h3>
  <table style="border-collapse:collapse;width:100%;font-size:14px">
    <tr style="color:#888;font-size:12px"><td style="padding:4px 10px">종목</td>
    <td style="padding:4px 10px;text-align:right">등락</td><td style="padding:4px 10px;text-align:right">비중</td></tr>
    {rows_html}
  </table>
  <h3 style="margin:22px 0 6px">주가 영향 주요 뉴스 (한국어 요약)</h3>
  <ul style="padding-left:18px;margin:0">{news_html}</ul>
  <p style="color:#aaa;font-size:12px;margin-top:22px;line-height:1.5">
    ⚠️ 예상 변동폭은 직전 미국 종가·환율 기반 단순 추정치입니다. 장중 미국 선물·환율·괴리율에 따라
    실제 값은 달라집니다. <b>투자 자문이 아니며 참고용입니다.</b></p>
</div>"""


# --------------------------- Gmail 발송 ---------------------------

def send_gmail(subject, html, text):
    addr = os.environ.get("GMAIL_ADDRESS")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("MAIL_TO") or addr
    if not addr or not pw:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD 환경변수가 필요합니다.")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = addr
    msg["To"] = to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(addr, pw)
        s.sendmail(addr, [x.strip() for x in to.split(",")], msg.as_string())
    return to


# --------------------------- 메인 ---------------------------

def main():
    no_send = "--no-send" in sys.argv
    cfg = load_config()
    kor = cfg.get("ticker_korean", {})
    basket, src = fetch_basket(cfg)
    print(f"PDP 출처: {src} ({len(basket)}종목)")
    prices = fetch_prices([h["ticker"] for h in basket])
    res = compute_expected(basket, prices)
    top_news = collect_top_news(res["rows"], top_n=6)

    console = render_console(res, top_news, kor)
    print("=" * 56); print(console); print("=" * 56)

    if no_send:
        print("\n[--no-send] 발송 생략.")
        # 미리보기 HTML 저장
        with open(os.path.join(HERE, "preview.html"), "w", encoding="utf-8") as f:
            f.write(render_html(res, top_news, kor))
        print("preview.html 저장됨.")
        return

    subject = f"[우주테크] {dt.date.today():%m/%d} 예상 {fmt_pct(res['expected'])}"
    to = send_gmail(subject, render_html(res, top_news, kor), console)
    print(f"\nGmail 발송 완료 → {to}")


if __name__ == "__main__":
    main()
