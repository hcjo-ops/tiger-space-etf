#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Pages용 모바일 웹뷰 생성기 (트리맵 버전).
- 구성종목 트리맵: 박스 면적=비중, 색=전일 등락(상승 빨강/하락 파랑, 진할수록 큼), 박스 내 5일 스파크라인.
- 상단: 오늘 예상 변동폭 / 괴리율(네이버) / 합성 NAV 5일 수익률 + 5일 추세.
- 하단: 한국어 뉴스. 기존 tiger_space_alert.py 로직 재사용.
"""
import os, json, datetime as dt, urllib.request
import yfinance as yf
import tiger_space_alert as t

def fetch_series(tickers):
    syms = list(dict.fromkeys(tickers)) + ["KRW=X"]
    df = yf.download(syms, period="12d", progress=False, auto_adjust=False)["Close"]
    per = {}
    for s in syms:
        ser = df[s].dropna() if s in df else None
        if ser is None or len(ser) < 2:
            per[s] = None; continue
        last, prev = float(ser.iloc[-1]), float(ser.iloc[-2])
        per[s] = {"last": last, "prev": prev,
                  "pct": (last-prev)/prev*100 if prev else 0,
                  "series": [float(v) for v in ser.iloc[-5:]],
                  "date": str(ser.index[-1].date())}
    return df, per

def fetch_deviation():
    try:
        u="https://m.stock.naver.com/api/stock/0183J0/etfAnalysis"
        r=urllib.request.Request(u, headers={"User-Agent":"Mozilla/5.0","Referer":"https://m.stock.naver.com/"})
        j=json.loads(urllib.request.urlopen(r,timeout=15).read().decode())
        rate=float(j.get("deviationRate"))
        sign=-1 if str(j.get("deviationSign","")).strip() in ("-","5","FALLING") else 1
        return sign*rate
    except Exception:
        return None

def nav_series(basket, df):
    tks=[h["ticker"] for h in basket]
    cols=[c for c in tks if c in df]+(["KRW=X"] if "KRW=X" in df else [])
    sub=df[cols].dropna()
    if len(sub)<2: return [],[]
    sub=sub.iloc[-6:]; sh={h["ticker"]:h["shares"] for h in basket}
    vals,dates=[],[]
    for idx,row in sub.iterrows():
        usd=sum(sh[tk]*row[tk] for tk in tks if tk in sub.columns)
        fx=row["KRW=X"] if "KRW=X" in sub.columns else 1.0
        vals.append(usd*fx); dates.append(str(idx.date()))
    return dates,vals

def _layout(sizes,x,y,dx,dy):
    if dx>=dy:
        cov=sum(sizes); w=cov/dy if dy else 0; out=[]; yy=y
        for s in sizes:
            dd=s/w if w else 0; out.append({"x":x,"y":yy,"dx":w,"dy":dd}); yy+=dd
        return out
    cov=sum(sizes); h=cov/dx if dx else 0; out=[]; xx=x
    for s in sizes:
        dd=s/h if h else 0; out.append({"x":xx,"y":y,"dx":dd,"dy":h}); xx+=dd
    return out

def _worst(sizes,x,y,dx,dy):
    rs=_layout(sizes,x,y,dx,dy)
    return max(max(r["dx"]/r["dy"],r["dy"]/r["dx"]) for r in rs if r["dx"]>0 and r["dy"]>0)

def _leftover(sizes,x,y,dx,dy):
    if dx>=dy:
        w=sum(sizes)/dy if dy else 0; return (x+w,y,dx-w,dy)
    h=sum(sizes)/dx if dx else 0; return (x,y+h,dx,dy-h)

def squarify(sizes,x,y,dx,dy):
    sizes=[float(s) for s in sizes]
    if not sizes: return []
    if len(sizes)==1: return _layout(sizes,x,y,dx,dy)
    i=1
    while i<len(sizes) and _worst(sizes[:i],x,y,dx,dy)>=_worst(sizes[:i+1],x,y,dx,dy):
        i+=1
    cur,rem=sizes[:i],sizes[i:]; rect=_leftover(cur,x,y,dx,dy)
    return _layout(cur,x,y,dx,dy)+squarify(rem,*rect)

def _hx(c): return tuple(int(c[i:i+2],16) for i in (1,3,5))
UP,DOWN,NEU=_hx("#d32f2f"),_hx("#1565c0"),_hx("#9aa0a8")
def color_for(pct):
    if pct is None: return "#6b7280","#ffffff"
    base=UP if pct>=0 else DOWN; tt=min(abs(pct)/5.0,1.0)
    start=tuple(NEU[i]+(base[i]-NEU[i])*0.30 for i in range(3))
    col=tuple(start[i]+(base[i]-start[i])*tt for i in range(3))
    lum=0.2126*col[0]+0.7152*col[1]+0.0722*col[2]
    return "#%02x%02x%02x"%tuple(int(round(v)) for v in col), ("#ffffff" if lum<150 else "#16181d")

def esc(s): return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def fmt(v,nd=2): return ("+" if v>=0 else "")+f"{v:.{nd}f}%"

def spark_points(series,x,y,w,h):
    n=len(series)
    if n<2: return ""
    mn,mx=min(series),max(series); rng=(mx-mn) or 1; pts=[]
    for i,v in enumerate(series):
        px=x+w*(i/(n-1)); py=y+h-(v-mn)/rng*h; pts.append(f"{px:.1f},{py:.1f}")
    return " ".join(pts)

def render_treemap(rows,W=1000,H=720):
    items=[r for r in rows if r.get("weight")]; items.sort(key=lambda r:r["weight"],reverse=True)
    sizes=[r["weight"] for r in items]; tot=sum(sizes); norm=[s/tot*(W*H) for s in sizes]
    rects=squarify(norm,0,0,W,H)
    svg=[f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" style="display:block;border-radius:12px;overflow:hidden;font-family:Arial,sans-serif">']
    for r,rc in zip(items,rects):
        x,y,dx,dy=rc["x"],rc["y"],rc["dx"],rc["dy"]; fill,txt=color_for(r["pct"])
        svg.append(f'<g><rect x="{x:.1f}" y="{y:.1f}" width="{dx:.1f}" height="{dy:.1f}" fill="{fill}" stroke="#0e1116" stroke-width="2"/>')
        big=min(dx,dy); fs=max(11,min(big*0.26,40)); cx,cy=x+dx/2,y+dy/2
        pct_txt="N/A" if r["pct"] is None else fmt(r["pct"],1)
        if dx>130 and dy>110 and r.get("series") and len(r["series"])>=2:
            pad=big*0.10; sh=dy*0.26; sx,sy,sw=x+pad,y+dy-sh-pad*0.6,dx-2*pad
            pts=spark_points(r["series"],sx,sy,sw,sh)
            stroke="rgba(255,255,255,.85)" if txt=="#ffffff" else "rgba(0,0,0,.55)"
            svg.append(f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')
            cy=y+dy*0.36
        svg.append(f'<text x="{cx:.1f}" y="{cy:.1f}" fill="{txt}" font-size="{fs:.0f}" font-weight="700" text-anchor="middle">{esc(r["ticker"])}</text>')
        svg.append(f'<text x="{cx:.1f}" y="{cy+fs*0.95:.1f}" fill="{txt}" font-size="{fs*0.7:.0f}" text-anchor="middle">{pct_txt}</text>')
        if dx>90 and dy>70:
            svg.append(f'<text x="{x+6:.1f}" y="{y+dy-6:.1f}" fill="{txt}" font-size="{max(9,fs*0.42):.0f}" opacity="0.85">{r["weight"]:.1f}%</text>')
        svg.append('</g>')
    svg.append('</svg>'); return "".join(svg)

def chip(label,value,color,sub=""):
    return (f'<div style="flex:1;min-width:96px;background:#f7f8fa;border-radius:12px;padding:10px 12px;text-align:center">'
            f'<div style="font-size:11px;color:#888">{label}</div>'
            f'<div style="font-size:20px;font-weight:800;color:{color}">{value}</div>'
            f'<div style="font-size:11px;color:#999">{sub}</div></div>')

def mini_spark(series,w=180,h=40):
    if not series or len(series)<2: return ""
    col="#d32f2f" if series[-1]>=series[0] else "#1565c0"
    pts=spark_points(series,2,2,w-4,h-4)
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}"><polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>')

def render_page(res,news,asof,deviation,nav5_ret,nav5_series):
    exp=res["expected"]; exp_c="#d32f2f" if exp>=0 else "#1565c0"
    dev_txt="N/A" if deviation is None else fmt(deviation,2)
    dev_c="#888" if deviation is None else ("#d32f2f" if deviation>=0 else "#1565c0")
    nav_c="#d32f2f" if (nav5_ret or 0)>=0 else "#1565c0"
    nav_txt="N/A" if nav5_ret is None else fmt(nav5_ret,2)
    treemap=render_treemap(res["rows"])
    news_html=""
    for _,tk,n in news:
        title=esc(n.get("title_ko",n["title"]))
        news_html+=(f'<li style="margin:10px 0;line-height:1.5"><a href="{n["link"]}" style="color:#1a4fbf;text-decoration:none;font-weight:600">{title}</a>'
                    f'<div style="color:#999;font-size:12px">[{tk}] {esc(n["source"])}</div></li>')
    now_kst=(dt.datetime.utcnow()+dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="우주테크">
<meta name="theme-color" content="#0b1020">
<title>TIGER 미국우주테크 데일리</title>
<style>
 html,body{{margin:0;background:#eef0f3;-webkit-text-size-adjust:100%;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#222}}
 .wrap{{max-width:680px;margin:auto;padding:14px 12px 30px}}
 .card{{background:#fff;border-radius:16px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.06);margin-bottom:14px}}
 h2{{margin:0 0 4px;font-size:20px}} h3{{margin:0 0 8px;font-size:16px}}
 .legend{{display:flex;gap:10px;justify-content:center;font-size:11px;color:#888;margin-top:10px;flex-wrap:wrap}}
 .sw{{display:inline-block;width:11px;height:11px;border-radius:2px;vertical-align:-1px;margin-right:3px}}
</style></head>
<body><div class="wrap">
 <div class="card">
   <h2>🚀 TIGER 미국우주테크</h2>
   <div style="color:#888;font-size:13px;margin-bottom:12px">{dt.date.today():%Y/%m/%d} · 기준 미국 {asof} 종가</div>
   <div style="display:flex;gap:8px;flex-wrap:wrap">
     {chip("오늘 예상 변동", fmt(exp), exp_c, f"종목 {fmt(res['stock'])} / 환율 {fmt(res['fx'])}")}
     {chip("괴리율", dev_txt, dev_c, "시장가 vs NAV(전일)")}
     {chip("NAV 5일", nav_txt, nav_c, "합성 기준")}
   </div>
   <div style="text-align:center;margin-top:10px">{mini_spark(nav5_series)}
     <div style="font-size:11px;color:#aaa">합성 NAV 최근 5거래일 추세</div></div>
 </div>
 <div class="card">
   <h3>구성종목 트리맵 <span style="font-size:12px;color:#999;font-weight:400">(박스=비중, 색=전일등락)</span></h3>
   {treemap}
   <div class="legend">
     <span><span class="sw" style="background:#d32f2f"></span>상승</span>
     <span><span class="sw" style="background:#1565c0"></span>하락</span>
     <span>박스 안 선 = 최근 5일 추세</span>
   </div>
 </div>
 <div class="card">
   <h3>주가 영향 주요 뉴스 (한국어)</h3>
   <ul style="padding-left:18px;margin:0">{news_html}</ul>
 </div>
 <div style="color:#aaa;font-size:12px;line-height:1.5;padding:0 4px">
   ⚠️ 예상 변동폭·괴리율은 직전 미국 종가·환율·전일 기준 추정/참고치입니다. 장중 값은 달라집니다. <b>투자 자문이 아니며 참고용입니다.</b>
   <div style="text-align:center;color:#bbb;margin-top:12px">마지막 업데이트 {now_kst} KST · 매 평일 아침 자동 갱신</div>
 </div>
</div></body></html>"""

def main():
    cfg=t.load_config(); kor=cfg.get("ticker_korean",{})
    basket,src=t.fetch_basket(cfg); print(f"PDP 출처: {src} ({len(basket)}종목)")
    df,per=fetch_series([h["ticker"] for h in basket])
    navL=navP=0.0; rows=[]
    for h in basket:
        p=per.get(h["ticker"]); kn=kor.get(h["ticker"],h["name"])
        if not p:
            rows.append({"ticker":h["ticker"],"name":h["name"],"kor":kn,"pct":None,"weight":None,"series":None}); continue
        navL+=h["shares"]*p["last"]; navP+=h["shares"]*p["prev"]
        rows.append({"ticker":h["ticker"],"name":h["name"],"kor":kn,"pct":p["pct"],"mv":h["shares"]*p["last"],"series":p["series"]})
    for r in rows:
        if r.get("mv") is not None and navL: r["weight"]=r["mv"]/navL*100
    stock=(navL-navP)/navP*100 if navP else 0
    fx=per.get("KRW=X"); fxr=fx["pct"] if fx else 0
    asof=next((per[h["ticker"]]["date"] for h in basket if per.get(h["ticker"])),"")
    rows.sort(key=lambda r:(r.get("weight") or 0),reverse=True)
    res={"expected":stock+fxr,"stock":stock,"fx":fxr,"rows":rows}
    deviation=fetch_deviation()
    _,navs=nav_series(basket,df)
    nav5_ret=((navs[-1]/navs[0]-1)*100) if len(navs)>=2 else None
    news=t.collect_top_news([{"ticker":r["ticker"],"name":r["name"],"pct":r["pct"]} for r in rows],top_n=6)
    html=render_page(res,news,asof,deviation,nav5_ret,navs)
    out=os.environ.get("OUT","site/index.html")
    os.makedirs(os.path.dirname(out) or ".",exist_ok=True)
    open(out,"w",encoding="utf-8").write(html)
    print("생성 완료:",out,"| 괴리율",deviation,"| NAV5",nav5_ret)

if __name__=="__main__":
    main()
