from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import sqlite3, datetime as dt, math, os, time, threading
import requests

APP = FastAPI(title='TrendWatch Pro API')
APP.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
BASE = Path(__file__).resolve().parent
DB = Path(os.getenv('TRENDWATCH_DB', str(BASE/'trendwatch.sqlite3')))
TSET = 'https://cdn.tsetmc.com'
UA = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36','Accept':'application/json,text/plain,*/*','Referer':'https://www.tsetmc.com/'}
REFRESH_LOCK = threading.Lock()
LAST_STATUS = {'google':'waiting','money':'waiting','google_error':None,'money_error':None,'updated_at':None}

def db():
    c=sqlite3.connect(DB)
    c.execute('CREATE TABLE IF NOT EXISTS money(date TEXT PRIMARY KEY, real_value REAL, legal_value REAL)')
    return c

def tget(path, params=None):
    last=None
    for attempt in range(4):
        try:
            r=requests.get(TSET+path, params=params, headers=UA, timeout=(8,20))
            r.raise_for_status()
            data=r.json()
            if not isinstance(data, dict):
                raise RuntimeError('TSETMC returned non-object JSON')
            return data
        except Exception as e:
            last=e
            if attempt < 3: time.sleep(2*(attempt+1))
    raise RuntimeError(f'TSETMC {path}: {last}')

def save_money(real_value, legal_value):
    today=dt.date.today().isoformat()
    c=db(); c.execute('INSERT OR REPLACE INTO money(date,real_value,legal_value) VALUES(?,?,?)',(today,real_value,legal_value)); c.commit(); c.close()

def collect_today_money():
    mw=tget('/api/ClosingPrice/GetMarketWatch', {'market':0,'industrialGroup':'','paperTypes[0]':1,'paperTypes[1]':2,'paperTypes[2]':3,'paperTypes[3]':4,'paperTypes[4]':5,'paperTypes[5]':6,'paperTypes[6]':7,'paperTypes[7]':8,'paperTypes[8]':9,'showTraded':'false','withBestLimits':'false','hEven':0,'RefID':0})
    rows=mw.get('marketwatch',[]) or []
    if not rows: raise RuntimeError('TSETMC MarketWatch returned no rows')
    prices={str(x.get('insCode') or x.get('inscode')): float(x.get('pClosing') or x.get('pl') or x.get('pDrCotVal') or 0) for x in rows if (x.get('insCode') or x.get('inscode'))}
    ct=tget('/api/ClientType/GetClientTypeAll')
    clients=ct.get('clientTypeAllDto',[]) or []
    if not clients: raise RuntimeError('TSETMC ClientTypeAll returned no rows')
    real=legal=0.0
    for x in clients:
        code=str(x.get('insCode') or x.get('inscode') or x.get('ins_code') or '')
        p=prices.get(code,0)
        if not p: continue
        bi=float(x.get('buy_I_Volume') or x.get('n_buy_volume') or 0); si=float(x.get('sell_I_Volume') or x.get('n_sell_volume') or 0)
        bn=float(x.get('buy_N_Volume') or x.get('l_buy_volume') or 0); sn=float(x.get('sell_N_Volume') or x.get('l_sell_volume') or 0)
        real+=(bi-si)*p; legal+=(bn-sn)*p
    if real == 0 and legal == 0: raise RuntimeError('TSETMC flow calculation returned zero')
    save_money(real,legal)
    return real,legal

def collect_google():
    from pytrends.request import TrendReq
    pt=TrendReq(hl='fa-IR',tz=210,timeout=(8,20),retries=1,backoff_factor=0.5)
    trends={}
    for term in ['بورس','طلا','دلار']:
        pt.build_payload([term],cat=0,timeframe='today 12-m',geo='IR',gprop='')
        df=pt.interest_over_time()
        arr=[]
        for idx,row in df.iterrows():
            val=row.get(term)
            if val is not None and not (isinstance(val,float) and math.isnan(val)):
                arr.append({'date':idx.date().isoformat(),'value':int(val),'real':True})
        if not arr: raise RuntimeError(f'Google Trends returned no data for {term}')
        trends[term]=arr
    return trends

def refresh_data():
    if not REFRESH_LOCK.acquire(blocking=False):
        return
    try:
        LAST_STATUS['money']='loading'; LAST_STATUS['money_error']=None
        try:
            collect_today_money()
            LAST_STATUS['money']='ok'
        except Exception as e:
            LAST_STATUS['money']='error'; LAST_STATUS['money_error']=str(e)[:250]
        LAST_STATUS['google']='loading'; LAST_STATUS['google_error']=None
        try:
            trends=collect_google()
            LAST_STATUS['google']='ok'
            LAST_STATUS['google_error']=None
            c=db()
            c.execute('CREATE TABLE IF NOT EXISTS google(date TEXT, term TEXT, value INTEGER, PRIMARY KEY(date,term))')
            for term,arr in trends.items():
                for x in arr:
                    c.execute('INSERT OR REPLACE INTO google(date,term,value) VALUES(?,?,?)',(x['date'],term,x['value']))
            c.commit(); c.close()
        except Exception as e:
            LAST_STATUS['google']='error'; LAST_STATUS['google_error']=str(e)[:250]
        LAST_STATUS['updated_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        print(f'DATA REFRESH: money={LAST_STATUS["money"]} google={LAST_STATUS["google"]}', flush=True)
    finally:
        REFRESH_LOCK.release()

@APP.on_event('startup')
def startup():
    print('TRENDWATCH PRO 5.2 LIVE DATA STARTED', flush=True)
    print('COLLECTOR CHECK STARTED', flush=True)
    threading.Thread(target=refresh_data, daemon=True).start()

@APP.get('/api/version')
def version_check():
    return {'build':'TWPRO-5.2-LIVE-20260918-B','server':'server.py','manifest':True,'collector':'background-nonblocking'}

@APP.get('/api/health')
def health():
    return {'ok':True,'service':'TrendWatch Pro API','version':'5.2-live-data','database':str(DB),'collector':'background-nonblocking','status':LAST_STATUS}

@APP.get('/manifest.json')
def manifest():
    return JSONResponse({'name':'TrendWatch Pro','short_name':'TrendWatch Pro','start_url':'/','display':'standalone','background_color':'#0b1020','theme_color':'#0b1020'})

@APP.get('/api/dashboard-data')
def dashboard_data(range: str='12m', days:int=30):
    # Never wait for external providers here. Return cached real data immediately.
    trends={}
    try:
        c=db()
        c.execute('CREATE TABLE IF NOT EXISTS google(date TEXT, term TEXT, value INTEGER, PRIMARY KEY(date,term))')
        for term in ['بورس','طلا','دلار']:
            rows=c.execute('SELECT date,value FROM google WHERE term=? ORDER BY date DESC LIMIT ?', (term,max(1,min(days,365)))).fetchall()
            trends[term]=[{'date':d,'value':int(v),'real':True} for d,v in reversed(rows)]
        c.close()
    except Exception:
        trends={'بورس':[],'طلا':[],'دلار':[]}
    try:
        c=db()
        rows=c.execute('SELECT date,real_value,legal_value FROM money ORDER BY date DESC LIMIT ?', (max(1,min(days,365)),)).fetchall()
        c.close(); rows=list(reversed(rows))
    except Exception:
        rows=[]
    return {
        'google_trends':trends,
        'real_money':[{'date':d,'value':round(v/1e10,2),'real':True} for d,v,l in rows],
        'legal_money':[{'date':d,'value':round(l/1e10,2),'real':True} for d,v,l in rows],
        'source':{'google':'Google Trends','money':'TSETMC ClientTypeAll + MarketWatch'},
        'status':{'google':'ok' if any(trends.values()) else LAST_STATUS['google'],'money':'ok' if rows else LAST_STATUS['money']},
        'errors':{'google':LAST_STATUS['google_error'],'money':LAST_STATUS['money_error']},
        'generated_at':dt.datetime.now(dt.timezone.utc).isoformat()
    }


RELAY_BASE = os.getenv('TSETMC_RELAY_URL', '').rstrip('/')

@APP.get('/api/history-by-symbol')
def history_by_symbol(symbol: str = ''):
    symbol = symbol.strip()
    if not symbol:
        return JSONResponse({'ok': False, 'error': 'symbol is required'}, status_code=400)
    if not RELAY_BASE:
        return JSONResponse({'ok': False, 'error': 'TSETMC_RELAY_URL is not configured'}, status_code=503)
    try:
        r = requests.get(
            RELAY_BASE + '/api/history-by-symbol',
            params={'symbol': symbol},
            timeout=(5, 45),
        )
        r.raise_for_status()
        data = r.json()
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=502)

@APP.get('/')
def index():
    return FileResponse(BASE/'TrendWatch_Pro_Mobile_v5_2.html')
