import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
from datetime import timedelta, timezone
import datetime 
from supabase import create_client, Client
import time
import re
import extra_streamlit_components as stx
import plotly.express as px

# --- 頁面基本設定 ---
st.set_page_config(page_title="個人資產紀錄網", layout="wide", page_icon="📈")

# ==========================================
# 🍪 Cookie 管理器初始化
# ==========================================
cookie_manager = stx.CookieManager(key="my_cookies")

# ==========================================
# 🚀 雲端資料庫 Supabase 初始化
# ==========================================
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# ==========================================
# 🔐 Google 登入防護網
# ==========================================
def login_ui():
    cookies = cookie_manager.get_all()
    if cookies is None:
        st.info("🔄 正在讀取您的安全憑證...")
        return False
    saved_email = cookies.get("user_email") if isinstance(cookies, dict) else None
    if "user_email" in st.session_state:
        return True
    elif saved_email:
        st.session_state["user_email"] = saved_email
        return True
    if "code" in st.query_params:
        try:
            code = st.query_params["code"]
            res = supabase.auth.exchange_code_for_session({"auth_code": code})
            email = res.user.email
            st.session_state["user_email"] = email
            cookie_manager.set("user_email", email, max_age=30*24*60*60)
            st.query_params.clear()
            time.sleep(1); st.rerun()
            return True
        except: pass
    st.markdown("<h1 style='text-align: center;'>🛋️ 個人資產紀錄網</h1>", unsafe_allow_html=True)
    res = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": "https://reid-stock.streamlit.app/"}})
    st.link_button("🚀 用 Google 帳號安全登入", res.url, type="primary", use_container_width=True)
    return False

if not login_ui(): st.stop()

# ==========================================
# 🗄️ 資料庫讀寫邏輯
# ==========================================
user_email = st.session_state["user_email"]
def load_data():
    res = supabase.table("user_data").select("*").eq("email", user_email).execute()
    if len(res.data) == 0:
        d = {"fee_discount": 6.0, "pledge_amount": 0.0, "account_balance": 0.0, "credit_loan": 0.0, "other_assets": 0.0, "buy_records": [], "realized_records": [], "history": {}, "market_data": {}, "futures_capital": 0.0, "futures_records": [], "futures_realized": [], "fee_fut_tx": 50.0, "fee_fut_mtx": 25.0}
        supabase.table("user_data").insert({"email": user_email, "data": d}).execute()
        return d
    return res.data[0]["data"]

def save_data(data):
    supabase.table("user_data").update({"data": data}).eq("email", user_email).execute()

db = load_data()
# 防呆補齊
for k in ["market_data", "futures_records", "buy_records", "history"]:
    if k not in db: db[k] = {} if k in ["market_data", "history"] else []

# --- 🚀 爬蟲引擎 ---
def fetch_price(ticker):
    price, name = 0.0, ticker
    t_l = ticker.lower()
    for url, tag in [(f"https://www.wantgoo.com/stock/{t_l}", 'span'), (f"https://www.wantgoo.com/futures/{t_l}", 'div')]:
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            soup = BeautifulSoup(resp.text, 'html.parser')
            node = soup.find(tag, class_='deal', attrs={'c-model': 'close'})
            if node and node.text.strip() != "--":
                price = float(node.text.replace(',', ''))
                nh3 = soup.find('h3', attrs={'c-model': 'name'})
                if nh3: name = nh3.text.strip()
                break
        except: pass
    return price, name

def calc_futures_cost(mult, p, lots):
    fee = float(db.get("fee_fut_tx", 50.0)) if mult == 200 else float(db.get("fee_fut_mtx", 25.0))
    return (fee * lots) + (p * mult * lots * 0.00002)

# --- 彈出視窗 ---
@st.dialog("⚙️ 設定")
def show_settings():
    new_d = st.number_input("股票手續費折數", value=float(db.get("fee_discount", 6.0)))
    new_tx = st.number_input("大台手續費", value=float(db.get("fee_fut_tx", 50.0)))
    new_mtx = st.number_input("小台手續費", value=float(db.get("fee_fut_mtx", 25.0)))
    if st.button("儲存"):
        db["fee_discount"], db["fee_fut_tx"], db["fee_fut_mtx"] = new_d, new_tx, new_mtx
        save_data(db); st.rerun()

@st.dialog("➕ 股")
def add_stock():
    d, t = st.date_input("日期"), st.text_input("代號").upper()
    s, p = st.number_input("股數", min_value=1), st.number_input("單價", min_value=0.01)
    if st.button("新增"):
        pr, na = fetch_price(t); db["market_data"][t] = {"price": pr, "name": na}
        db["buy_records"].append({"id": int(time.time()), "date": str(d), "ticker": t, "shares": s, "price": p})
        save_data(db); st.rerun()

@st.dialog("➕ 期")
def add_futures():
    d, t = st.date_input("日期"), st.text_input("代號", placeholder="期貨請加 W").upper()
    dir = 1 if "多" in st.selectbox("方向", ["多", "空"]) else -1
    m_str = st.selectbox("規格", ["大台 (200)", "小台 (50)", "微台 (10)", "股期 (2000)"])
    mult = int(re.search(r'\((\d+)\)', m_str).group(1))
    l, p = st.number_input("口數", min_value=1), st.number_input("成交價")
    if st.button("新增"):
        with st.spinner("抓取名稱..."): pr, na = fetch_price(t)
        db["futures_records"].append({"id": int(time.time()), "ticker": t, "name": na, "direction": dir, "multiplier": mult, "lots": l, "price": p})
        db["market_data"][t] = {"price": pr if pr > 0 else p, "name": na}
        save_data(db); st.rerun()

# --- 核心計算 ---
tot_mv, stock_unrealized, display_stocks = 0, 0, []
for r in db["buy_records"]:
    t = r["ticker"]
    curr = db["market_data"].get(t, {"price": 0.0, "name": t})
    mv = r["shares"] * curr["price"]; tot_mv += mv
    cost = r["shares"] * r["price"] * (1 + 0.001425 * (db["fee_discount"]/10))
    tax = mv * (0.001 if t.startswith("00") else 0.003)
    un = round(mv - (mv * 0.001425 * (db["fee_discount"]/10)) - tax - cost)
    stock_unrealized += un
    display_stocks.append({"ticker": t, "name": curr["name"], "mv": mv, "un": un})

fut_unrealized, fut_exp = 0, 0
for f in db["futures_records"]:
    cp = db["market_data"].get(f["ticker"], {"price": f["price"]})["price"]
    gross = (cp - f["price"]) * f["direction"] * f["multiplier"] * f["lots"]
    un = round(gross - calc_futures_cost(f["multiplier"], f["price"], f["lots"]) - calc_futures_cost(f["multiplier"], cp, f["lots"]))
    fut_unrealized += un; fut_exp += (cp * f["multiplier"] * f["lots"])

total_assets = float(db["account_balance"]) + tot_mv + float(db["other_assets"]) + (float(db["futures_capital"]) + fut_unrealized) - float(db["pledge_amount"]) - float(db["credit_loan"])
total_exposure = tot_mv + fut_exp
lev = total_exposure / total_assets if total_assets > 0 else 0
m_ratio = (tot_mv / float(db["pledge_amount"]) * 100) if float(db["pledge_amount"]) > 0 else 0

# --- UI 介面 ---
col_s, c_a, c_f, c_set, c_up, c_out = st.columns([4, 1, 1, 1, 1, 1])
if c_a.button("➕ 股"): add_stock()
if c_f.button("➕ 期"): add_futures()
if c_set.button("⚙️"): show_settings()
if c_up.button("🔄"):
    for t in {r["ticker"] for r in db["buy_records"]} | {f["ticker"] for f in db["futures_records"]}:
        p, n = fetch_price(t)
        if p > 0: db["market_data"][t] = {"price": p, "name": n}
    save_data(db); st.rerun()

m1, m2, m3 = st.columns(3)
m1.metric("槓桿倍數", f"{lev:.2f}x"); m2.metric("質押維持率", f"{m_ratio:.1f}%"); m3.metric("總曝險額", f"${total_exposure:,.0f}")

t1, t2, t3, t4, t5 = st.tabs(["📉 庫存", "⚡ 期貨", "📈 獲利走勢", "📊 資產走勢", "⚖️ 資金"])
with t1:
    df_p = pd.DataFrame(display_stocks)
    if not df_p.empty:
        fig = px.pie(df_p, values='mv', names='ticker', hole=0.6)
        fig.add_annotation(text=f"TWD<br>{tot_mv:,.0f}", showarrow=False, font_size=20)
        st.plotly_chart(fig, use_container_width=True)
with t3:
    if db["history"]:
        st.line_chart(pd.DataFrame([{"D": k, "P": v["profit"]} for k, v in db["history"].items()]).set_index("D"))
with t4:
    if db["history"]:
        st.line_chart(pd.DataFrame([{"D": k, "A": v["assets"]} for k, v in db["history"].items()]).set_index("D"))
with t5:
    nb = st.number_input("銀行餘額", value=float(db["account_balance"]))
    nfc = st.number_input("期貨本金", value=float(db["futures_capital"]))
    np = st.number_input("質押金額", value=float(db["pledge_amount"]))
    if st.button("💾 更新"):
        db["account_balance"], db["futures_capital"], db["pledge_amount"] = nb, nfc, np
        save_data(db); st.rerun()
