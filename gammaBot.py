

import datetime
import pandas as pd
import streamlit as st
import requests
import numpy as np
from datetime import date

# ======================
# SAXO BANK API CONFIG
# ======================
SAXO_ACCESS_TOKEN = "your_saxo_api_token_here"
SAXO_BASE_URL = "https://gateway.saxobank.com/api/openapi"
ACCOUNT_KEY = "your_saxo_account_key_here"

# ======================
# STRATEGY PARAMETERS
# ======================
US_WEEKLY_TICKERS = [
    "TSLA", "NVDA", "AMD", "META", "AMZN", "AAPL", "GOOGL",
    "MSFT", "NFLX", "PYPL", "INTC", "CSCO", "QCOM",
    "ZM", "DOCU", "SNAP", "ROKU", "SPOT", "UBER", "LYFT"
]
MOMENTUM_THRESHOLD = 0.01
BETA_THRESHOLD = 1.5
BENCHMARK_TICKER = "SPY"

# ======================
# UTILS
# ======================

def get_this_week_friday():
    today = date.today()
    return today + datetime.timedelta(days=(4 - today.weekday() % 7))

def get_uic(ticker):
    headers = {"Authorization": f"Bearer {SAXO_ACCESS_TOKEN}"}
    try:
        res = requests.get(
            f"{SAXO_BASE_URL}/ref/v1/lookup", params={"Keyword": ticker}, headers=headers
        )
        items = res.json().get("Data", [])
        for item in items:
            if item["AssetType"] == "Stock" and item["Symbol"] == ticker:
                return item["Uic"]
    except:
        pass
    return None

def get_saxo_stock_price(uic):
    headers = {"Authorization": f"Bearer {SAXO_ACCESS_TOKEN}"}
    params = {"AssetType": "Stock", "Uic": uic}
    try:
        res = requests.get(f"{SAXO_BASE_URL}/trade/v1/infoprices", headers=headers, params=params)
        if res.status_code == 200:
            return res.json().get("LastTraded", {}).get("Price")
    except:
        pass
    return None

def get_last_two_closes(uic):
    headers = {"Authorization": f"Bearer {SAXO_ACCESS_TOKEN}"}
    params = {
        "Uic": uic,
        "AssetType": "Stock",
        "FieldGroups": "Data",
        "Interval": "OneDay",
        "Count": 2
    }
    try:
        res = requests.get(f"{SAXO_BASE_URL}/chart/v1/charts", headers=headers, params=params)
        points = res.json().get("Data", {}).get("DataPoints", [])
        closes = [p["Close"] for p in points if "Close" in p]
        if len(closes) == 2:
            return closes
    except:
        pass
    return None

def calculate_beta(stock_uic, benchmark_uic):
    headers = {"Authorization": f"Bearer {SAXO_ACCESS_TOKEN}"}
    params = {
        "FieldGroups": "Data",
        "Interval": "OneDay",
        "Count": 60
    }
    try:
        params["Uic"] = stock_uic
        params["AssetType"] = "Stock"
        stock_res = requests.get(f"{SAXO_BASE_URL}/chart/v1/charts", headers=headers, params=params)
        stock_points = stock_res.json().get("Data", {}).get("DataPoints", [])
        stock_closes = [p["Close"] for p in stock_points if "Close" in p]

        params["Uic"] = benchmark_uic
        params["AssetType"] = "Stock"
        bench_res = requests.get(f"{SAXO_BASE_URL}/chart/v1/charts", headers=headers, params=params)
        bench_points = bench_res.json().get("Data", {}).get("DataPoints", [])
        bench_closes = [p["Close"] for p in bench_points if "Close" in p]

        if len(stock_closes) == len(bench_closes):
            stock_returns = np.diff(stock_closes) / stock_closes[:-1]
            bench_returns = np.diff(bench_closes) / bench_closes[:-1]
            cov = np.cov(stock_returns, bench_returns)[0][1]
            var = np.var(bench_returns)
            return cov / var
    except:
        pass
    return None

def find_weekly_atm_call(uic, price):
    headers = {"Authorization": f"Bearer {SAXO_ACCESS_TOKEN}"}
    expiry = get_this_week_friday().strftime("%Y-%m-%d")
    params = {
        "AssetType": "Option",
        "UnderlyingUic": uic,
        "OptionType": "Call",
        "StrikePriceNear": price,
        "ExpiryDate": expiry
    }
    try:
        res = requests.get(f"{SAXO_BASE_URL}/ref/v1/instruments", headers=headers, params=params)
        options = res.json().get("Data", [])
        return options[0] if options else None
    except:
        pass
    return None

def place_saxo_order(option_uic):
    headers = {
        "Authorization": f"Bearer {SAXO_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    order = {
        "AccountKey": ACCOUNT_KEY,
        "Uic": option_uic,
        "AssetType": "Option",
        "Amount": 1,
        "BuySell": "Buy",
        "OrderType": "Market",
        "OrderDuration": {"DurationType": "DayOrder"}
    }
    try:
        res = requests.post(f"{SAXO_BASE_URL}/trade/v2/orders", headers=headers, json=order)
        return res.status_code == 201
    except:
        return False

# ======================
# STREAMLIT UI
# ======================
st.title("🚀 GammaBot - Only SAXO Version")
st.markdown("""
**Rules:**
- Weekly ATM calls
- Beta > 1.5 vs SPY
- Momentum > 1%
""")

signals = []
benchmark_uic = get_uic(BENCHMARK_TICKER)
for ticker in US_WEEKLY_TICKERS:
    uic = get_uic(ticker)
    if not uic or not benchmark_uic:
        continue

    beta = calculate_beta(uic, benchmark_uic)
    if not beta or beta <= BETA_THRESHOLD:
        continue

    price = get_saxo_stock_price(uic)
    closes = get_last_two_closes(uic)
    if not price or not closes:
        continue

    change = (price - closes[0]) / closes[0]
    if change > MOMENTUM_THRESHOLD:
        option = find_weekly_atm_call(uic, price)
        if option:
            signals.append({
                "Ticker": ticker,
                "Beta": round(beta, 2),
                "Momentum": f"{change:.2%}",
                "Strike": option["StrikePrice"],
                "Premium": option.get("LastTraded", {}).get("Price", "N/A"),
                "Expiry": option["ExpiryDate"],
                "Uic": option["Uic"]
            })

if signals:
    df = pd.DataFrame(signals)
    st.dataframe(df)
    selected = st.selectbox("Select ticker:", df["Ticker"])
    if st.button("BUY CALL OPTION"):
        uic = df[df["Ticker"] == selected].iloc[0]["Uic"]
        if place_saxo_order(uic):
            st.success("Order executed!")
        else:
            st.error("Order failed")
else:
    st.warning("No valid signals found.")

st.caption(f"Updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
