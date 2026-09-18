from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import sqlite3, json, datetime as dt, math, os
import requests

APP=FastAPI(title='TrendWatch Pro API')
APP.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
BASE=Path(__file__).resolve().parent
DB=Path(os.getenv('TRENDWATCH_DB', str(BASE/'trendwatch.sqlite3')))
TSET='https://cdn.tsetmc.com'
UA={'User-Agent':'Mozilla/5.0 TrendWatchPro/5.2'}

def db():
    c=sqlite3.connect(DB)
    c.execute('CREATE TABLE IF NOT EXISTS money(date TEXT PRIMARY KEY, real_value REAL, legal_value REAL)')
    return c

def tget(path, params=None):
    last=None
    for attempt in range(3):
        try:
            r=requests.get(TSET+path,params=params,headers=UA,timeout=25)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last=e
            if attempt < 2:
                import time; time.sleep(1.5*(attempt+1))
    raise last

def save_money(real_value, legal_value):
    today=dt.date.today().isoformat(); c=db()
    c.execute('INSERT OR REPLACE INTO money(date,real_value,legal_value) VALUES(?,?,?)',(today,real_value,legal_value)); c.commit(); c.close()

def collect_today_money():
    mw=tget('/api/ClosingPrice/GetMarketWatch', {'market':0,'industrialGroup':'','paperTypes[0]':1,'paperTypes[1]':2,'paperTypes[2]':3,'paperTypes[3]':4,'paperTypes[4]':5,'paperTypes[5]':6,'paperTypes[6]':7,'paperTypes[7]':8,'paperTypes[8]':9,'showTraded':'false','withBestLimits':'false','hEven':0,'RefID':0})
    rows=mw.get('marketwatch',[])
    prices={str(x.get('insCode') or x.get('inscode')): float(x.get('pClosing') or x.get('pl') or x.get('pDrCotVal') or 0) for x in rows if (x.get('insCode') or x.get('inscode'))}
    ct=tget('/api/ClientType/GetClientTypeAll').get('clientTypeAllDto',[])
    real=legal=0.0
    for x in ct:
        code=str(x.get('insCode') or x.get('inscode') or x.get('ins_code') or ''); p=prices.get(code,0)
        if not p: continue
        bi=float(x.get('buy_I_Volume') or x.get('n_buy_volume') or 0); si=float(x.get('sell_I_Volume') or x.get('n_sell_volume') or 0)
        bn=float(x.get('buy_N_Volume') or x.get('l_buy_volume') or 0); sn=float(x.get('sell_N_Volume') or x.get('l_sell_volume') or 0)
        real+=(bi-si)*p; legal+=(bn-sn)*p
    save_money(real,legal); return real,legal

@APP.get('/api/health')
def health(): return {'ok':True,'service':'TrendWatch Pro API','version':'5.2-no-termux'}

@APP.get('/api/dashboard-data')
def dashboard_data(range: str='12m', days:int=30):
    trends={}; trend_error=None
    try:
        from pytrends.request import TrendReq
        pt=TrendReq(hl='fa-IR',tz=210,timeout=(10,30),retries=2,backoff_factor=0.5)
        for term in ['بورس','طلا','دلار']:
            pt.build_payload([term],cat=0,timeframe='today 12-m',geo='IR',gprop='')
            df=pt.interest_over_time(); arr=[]
            for idx,row in df.iterrows():
                val=row.get(term)
                if val is not None and not (isinstance(val,float) and math.isnan(val)):
                    arr.append({'date':idx.date().isoformat(),'value':int(val),'real':True})
            trends[term]=arr
    except Exception as e: trend_error=str(e)[:180]
    money_error=None
    try:
        today=dt.date.today().isoformat(); c0=db(); already=c0.execute('SELECT 1 FROM money WHERE date=?',(today,)).fetchone(); c0.close()
        if not already: collect_today_money()
    except Exception as e: money_error=str(e)[:180]
    c=db(); rows=c.execute('SELECT date,real_value,legal_value FROM money ORDER BY date DESC LIMIT ?', (max(1,min(days,365)),)).fetchall(); c.close(); rows=list(reversed(rows))
    return {'google_trends':trends,'real_money':[{'date':d,'value':round(v/1e10,2)} for d,v,l in rows],'legal_money':[{'date':d,'value':round(l/1e10,2)} for d,v,l in rows],'source':{'google':'Google Trends','money':'TSETMC ClientTypeAll + MarketWatch'},'status':{'google':'ok' if trends else 'error','money':'ok' if rows else 'error'},'errors':{'google':trend_error,'money':money_error},'generated_at':dt.datetime.now(dt.timezone.utc).isoformat()}

@APP.get('/')
def index(): return FileResponse(BASE/'TrendWatch_Pro_Mobile_v5_2.html')
