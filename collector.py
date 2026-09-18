"""
TrendWatch Pro - Independent Live Data Collector
Collects real TSETMC market flows and Google Trends data.
No demo, forecast, or synthetic values are generated.
"""
import os, time, math, datetime as dt
import requests

TSET = "https://cdn.tsetmc.com"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.tsetmc.com/",
}

def tget(path, params=None):
    last = None
    for attempt in range(4):
        try:
            r = requests.get(TSET + path, params=params, headers=UA, timeout=(10,35))
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"TSETMC {path}: {last}")

def collect_tsetmc():
    mw = tget("/api/ClosingPrice/GetMarketWatch", {
        "market":0, "industrialGroup":"",
        "paperTypes[0]":1, "paperTypes[1]":2, "paperTypes[2]":3,
        "paperTypes[3]":4, "paperTypes[4]":5, "paperTypes[5]":6,
        "paperTypes[6]":7, "paperTypes[7]":8, "paperTypes[8]":9,
        "showTraded":"false", "withBestLimits":"false", "hEven":0, "RefID":0
    })
    rows = mw.get("marketwatch", []) or []
    if not rows:
        raise RuntimeError("TSETMC MarketWatch returned no rows")

    prices = {
        str(x.get("insCode") or x.get("inscode")):
        float(x.get("pClosing") or x.get("pl") or x.get("pDrCotVal") or 0)
        for x in rows if x.get("insCode") or x.get("inscode")
    }

    ct = tget("/api/ClientType/GetClientTypeAll")
    clients = ct.get("clientTypeAllDto", []) or []
    if not clients:
        raise RuntimeError("TSETMC ClientTypeAll returned no rows")

    real = legal = 0.0
    for x in clients:
        code = str(x.get("insCode") or x.get("inscode") or x.get("ins_code") or "")
        price = prices.get(code, 0)
        if not price:
            continue
        buy_i = float(x.get("buy_I_Volume") or x.get("n_buy_volume") or 0)
        sell_i = float(x.get("sell_I_Volume") or x.get("n_sell_volume") or 0)
        buy_n = float(x.get("buy_N_Volume") or x.get("l_buy_volume") or 0)
        sell_n = float(x.get("sell_N_Volume") or x.get("l_sell_volume") or 0)
        real += (buy_i - sell_i) * price
        legal += (buy_n - sell_n) * price

    if real == 0 and legal == 0:
        raise RuntimeError("TSETMC flow calculation returned zero")

    return {
        "date": dt.date.today().isoformat(),
        "real_value": real,
        "legal_value": legal,
        "source": "TSETMC",
        "real": True
    }

def collect_google():
    from pytrends.request import TrendReq
    pt = TrendReq(hl="fa-IR", tz=210, timeout=(10,30), retries=2, backoff_factor=0.5)
    result = {}
    for term in ["بورس", "طلا", "دلار"]:
        pt.build_payload([term], timeframe="today 12-m", geo="IR", gprop="")
        df = pt.interest_over_time()
        arr = []
        for idx, row in df.iterrows():
            value = row.get(term)
            if value is not None and not (isinstance(value, float) and math.isnan(value)):
                arr.append({"date": idx.date().isoformat(), "value": int(value), "real": True})
        if not arr:
            raise RuntimeError(f"Google Trends returned no data for {term}")
        result[term] = arr
    return result

if __name__ == "__main__":
    print("TrendWatch Pro Collector")
    print("TSETMC:", collect_tsetmc())
    print("Google Trends:", {k: len(v) for k,v in collect_google().items()})
