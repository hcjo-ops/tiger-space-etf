#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Pages용 모바일 웹뷰 생성기.
기존 tiger_space_alert.py 의 로직을 재사용해 standalone HTML 한 장을 만든다.

사용법:
  python build_web.py            # site/index.html 생성
  OUT=docs/index.html python build_web.py
"""
import os
import datetime as dt
import tiger_space_alert as t


def main():
    cfg = t.load_config()
    kor = cfg.get("ticker_korean", {})
    basket, src = t.fetch_basket(cfg)
    print(f"PDP 출처: {src} ({len(basket)}종목)")
    prices = t.fetch_prices([h["ticker"] for h in basket])
    res = t.compute_expected(basket, prices)
    news = t.collect_top_news(res["rows"], top_n=6)
    inner = t.render_html(res, news, kor)

    now_kst = (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")
    out = os.environ.get("OUT", "site/index.html")

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="우주테크">
<meta name="theme-color" content="#0b1020">
<title>TIGER 미국우주테크 데일리</title>
<style>
  html,body{{margin:0;background:#f2f3f5;-webkit-text-size-adjust:100%}}
  .wrap{{padding:14px 12px 28px}}
  .card{{background:#fff;border-radius:16px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
  a{{-webkit-tap-highlight-color:transparent}}
</style>
</head>
<body>
  <div class="wrap"><div class="card">
    {inner}
    <div style="text-align:center;color:#bbb;font-size:12px;margin-top:18px">
      마지막 업데이트 {now_kst} KST · 매 평일 아침 자동 갱신
    </div>
  </div></div>
</body>
</html>"""

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("생성 완료:", out)


if __name__ == "__main__":
    main()
