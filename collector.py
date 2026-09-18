"""
TrendWatch Pro live collector.
Only real provider responses are written. Failed providers remain unavailable.
"""
import argparse, datetime as dt, json, math, time
import requests

TSET = "https://cdn.tsetmc.com"
UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.tsetmc.com/",
}

def tget(path, params=None):
    last = None
    for attempt in range(4):
        try:
            r = requests.get(TSET + path, params=params, headers=UA, timeout=(8,20))
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise RuntimeError("TSETMC returned non-object JSON")
            return data
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
    return {"date": dt.date.today().isoformat(), "real_value": real, "legal_value": legal, "source":"TSETMC", "real":True}

def collect_google():
    from pytrends.request import TrendReq
    pt = TrendReq(hl="fa-IR", tz=210, timeout=(8,20), retries=1, backoff_factor=0.5)
    result = {}
    for term in ["بورس","طلا","دلار"]:
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="live_data.json")
    args = ap.parse_args()
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "google_trends": {},
        "money": None,
        "errors": {},
        "all_real": True
    }

    try:
        out["google_trends"] = collect_google()
        print("GOOGLE: OK - real Google Trends data collected")
    except Exception as e:
        out["errors"]["google"] = str(e)[:1000]
        print(f"GOOGLE: ERROR - {out['errors']['google']}")

    try:
        out["money"] = collect_tsetmc()
        print("TSETMC: OK - real TSETMC data collected")
    except Exception as e:
        out["errors"]["money"] = str(e)[:1000]
        print(f"TSETMC: ERROR - {out['errors']['money']}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n=== TRENDWATCH COLLECTOR RESULT ===")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if out["google_trends"] or out["money"]:
        print("RESULT: At least one real provider returned data.")
    else:
        print("RESULT: NO REAL PROVIDER DATA. Details above and in live_data.json.")
    # Do not fail the workflow merely because an external provider is unavailable.
    # GitHub Actions can then commit the diagnostic live_data.json for inspection.

if __name__ == "__main__":
    main()
