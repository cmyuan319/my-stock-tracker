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
st.set_page_config(page_title="Reid 資產戰情室", layout="wide", page_icon="📈")

# ==========================================
# 📱 🚀 手機版視覺優化 CSS (vivo X300 Pro 專屬)
# ==========================================
st.markdown("""
    <style>
    /* 全域字體微調 */
    html, body, [class*="css"] {
        font-family: 'PingFang TC', 'Microsoft JhengHei', sans-serif;
    }
    
    /* 針對手機螢幕 (寬度小於 600px) 的魔術調整 */
    @media (max-width: 600px) {
        /* 1. 讓 Metric 指標卡片橫向並排，不要垂直堆疊 */
        [data-testid="stMetric"] {
            display: inline-block;
            width: 32% !important;
            padding: 5px !important;
            text-align: center;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.2rem !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.7rem !important;
        }
        
        /* 2. 縮小按鈕文字與間距 */
        .stButton button {
            width: 100% !important;
            padding: 0px !important;
            font-size: 13px !important;
            height: 2.5rem !important;
        }
        
        /* 3. 減少分頁標籤的間距 */
        .stTabs [data-baseweb="tab"] {
            padding-left: 10px !important;
            padding-right: 10px !important;
            font-size: 14px !important;
        }
        
        /* 4. 隱藏手機版不必要的空白 */
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 0rem !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

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
    if cookies is None: return False
    saved_email = cookies.get("user_email") if isinstance(cookies, dict) else None
    if "user_email" in st.session_state: return True
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
    st.markdown("<h1 style='text-align: center; color: #003366; margin-top: 50px;'>🛋️ Reid 資產紀錄網</h1>", unsafe_allow_html=True)
    res = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": "https://reid-stock.streamlit.app/"}})
    st.link_button("🚀 用 Google 帳號登入資料庫", res.url, type="primary", use_container_width=True)
    return False

if not login_ui(): st.stop()

# ==========================================
# 🗄️ 資料庫讀寫與自動補齊
# ==========================================
user_email = st.session_state["user_email"]
def load_data():
    res = supabase.table("user_data").select("*").eq("email", user_email).execute()
    defaults = {
        "fee_discount": 6.0, "pledge_amount": 0.0, "account_balance": 0.0, "credit_loan": 0.0, "other_assets": 0.0,
        "buy_records": [], "realized_records": [], "history": {}, "market_data": {},
        "futures_capital": 0.0, "futures_records": [], "futures_realized": [],
        "fee_fut_tx": 50.0, "fee_fut_mtx": 25.0, "fee_fut_tmf": 10.0, "fee_fut_stf": 20.0
    }
    if len(res.data) == 0:
        supabase.table("user_data").insert({"email": user_email, "data": defaults}).execute()
        return defaults
    data = res.data[0]["data"]
    updated = False
    for k, v in defaults.items():
        if k not in data: data[k] = v; updated = True
    if updated: save_data(data)
    return data

def save_data(data):
    supabase.table("user_data").update({"data": data}).eq("email", user_email).execute()

db = load_data()

# --- 🚀 爬蟲與精算引擎 ---
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

def calc_cost_profit(ticker, shares, buy_price, sell_price=None):
    disc = db.get("fee_discount", 6.0) / 10.0
    buy_cost = shares * buy_price
    buy_fee = buy_cost * 0.001425 * disc
    total_cost = buy_cost + buy_fee
    if sell_price is not None:
        sell_rev = shares * sell_price
        sell_fee = sell_rev * 0.001425 * disc
        tax_rate = 0.001 if ticker.startswith("00") else 0.003
        sell_tax = sell_rev * tax_rate
        return round(sell_rev - sell_fee - sell_tax - total_cost)
    return total_cost

def calc_futures_cost(multiplier, price, lots):
    if multiplier == 200: fee = float(db.get("fee_fut_tx", 50.0))
    elif multiplier == 50: fee = float(db.get("fee_fut_mtx", 25.0))
    elif multiplier == 10: fee = float(db.get("fee_fut_tmf", 10.0))
    elif multiplier in [100, 2000]: fee = float(db.get("fee_fut_stf", 20.0))
    else: fee = float(db.get("fee_fut_tx", 50.0)) 
    tax = price * multiplier * lots * 0.00002
    return (fee * lots) + tax

# --- 彈出視窗 ---
@st.dialog("⚙️ 設定中心")
def show_settings():
    new_disc = st.number_input("股票手續費折數", value=float(db["fee_discount"]))
    st.markdown("#### ⚡ 期貨手續費 (單邊)")
    c1, c2 = st.columns(2)
    ntx = c1.number_input("大台 (TX)", value=float(db["fee_fut_tx"]))
    nmtx = c2.number_input("小台 (MTX)", value=float(db["fee_fut_mtx"]))
    ntmf = c1.number_input("微台 (TMF)", value=float(db["fee_fut_tmf"]))
    nstf = c2.number_input("股期 (STF)", value=float(db["fee_fut_stf"]))
    if st.button("💾 儲存並關閉", type="primary", use_container_width=True):
        db["fee_discount"], db["fee_fut_tx"], db["fee_fut_mtx"], db["fee_fut_tmf"], db["fee_fut_stf"] = new_disc, ntx, nmtx, ntmf, nstf
        save_data(db); st.rerun()

@st.dialog("➕ 新增股票")
def add_stock():
    d, t = st.date_input("日期"), st.text_input("代號").upper()
    s, p = st.number_input("股數", min_value=1, step=1000), st.number_input("成交價", min_value=0.01)
    if st.button("確認新增", type="primary", use_container_width=True):
        if t:
            pr, na = fetch_price(t); db["market_data"][t] = {"price": pr, "name": na}
            db["buy_records"].append({"id": int(time.time()), "date": str(d), "ticker": t, "shares": s, "price": p})
            save_data(db); st.rerun()

@st.dialog("⚡ 新增期貨")
def add_futures():
    d, t = st.date_input("日期"), st.text_input("代號", placeholder="提示：期貨加 W").upper()
    dir = 1 if "多" in st.selectbox("方向", ["做多 (+1)", "做空 (-1)"]) else -1
    m_str = st.selectbox("規格", ["大台 (200)", "小台 (50)", "微台 (10)", "股票期貨 (2000)", "小型股期 (100)", "自訂"])
    mult = int(re.search(r'\((\d+)\)', m_str).group(1)) if "(" in m_str else st.number_input("自訂乘數", min_value=1)
    l, p = st.number_input("口數", min_value=1), st.number_input("成交價", min_value=0.01)
    if st.button("確認新增", type="primary", use_container_width=True):
        if t:
            with st.spinner("抓取名稱..."): pr, na = fetch_price(t)
            db["futures_records"].append({"id": int(time.time()), "date": str(d), "ticker": t, "name": na, "direction": dir, "multiplier": mult, "lots": l, "price": p})
            db["market_data"][t] = {"price": pr if pr > 0 else p, "name": na}
            save_data(db); st.rerun()

@st.dialog("🔍 股票明細")
def show_details(ticker, name):
    recs = sorted([r for r in db["buy_records"] if r["ticker"] == ticker], key=lambda x: x["date"], reverse=True)
    for r in recs:
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        c1.write(r["date"]); c2.write(f"{r['shares']:,}"); c3.write(f"${r['price']:.2f}")
        if c4.button("🗑️", key=f"del_{r['id']}"):
            db["buy_records"] = [x for x in db["buy_records"] if x["id"] != r["id"]]
            save_data(db); st.rerun()

@st.dialog("🛒 賣出股票")
def sell_stock(ticker, name):
    tot_s = sum(r["shares"] for r in db["buy_records"] if r["ticker"] == ticker)
    sd, ss = st.date_input("賣出日期"), st.number_input("股數", min_value=1, max_value=tot_s, step=1000)
    sp = st.number_input("單價", value=float(db["market_data"].get(ticker, {"price": 0.0})["price"]))
    if st.button("確認賣出", type="primary", use_container_width=True):
        rem = ss
        for r in sorted([x for x in db["buy_records"] if x["ticker"] == ticker], key=lambda x: x["date"]):
            if rem <= 0: break
            take = min(r["shares"], rem)
            db["realized_records"].append({"sell_date": str(sd), "ticker": ticker, "shares": take, "buy_price": r["price"], "sell_price": sp})
            r["shares"] -= take; rem -= take
        db["buy_records"] = [x for x in db["buy_records"] if x["shares"] > 0]
        save_data(db); st.rerun()

@st.dialog("🛒 期貨平倉")
def close_fut(f_id, f_name, lots, fdir):
    sd, sl, sp = st.date_input("日期"), st.number_input("口數", min_value=1, max_value=lots), st.number_input("價格", min_value=0.01)
    if st.button("確認平倉", type="primary", use_container_width=True):
        for r in db["futures_records"]:
            if r["id"] == f_id:
                db["futures_realized"].append({"sell_date": str(sd), "ticker": r["ticker"], "name": r["name"], "direction": r["direction"], "multiplier": r["multiplier"], "lots": sl, "buy_price": r["price"], "sell_price": sp})
                r["lots"] -= sl; break
        db["futures_records"] = [x for x in db["futures_records"] if x["lots"] > 0]
        save_data(db); st.rerun()

# --- 核心計算 ---
agg = {}
for r in db["buy_records"]:
    t = r["ticker"]
    if t not in agg: agg[t] = {"shares": 0, "cost": 0}
    agg[t]["shares"] += r["shares"]; agg[t]["cost"] += r["shares"] * r["price"]

tot_exp, tot_mv, stock_unrealized, display_stocks = 0, 0, 0, []
for t, d in agg.items():
    shares = d["shares"]
    info = db["market_data"].get(t, {"price": 0.0, "name": t})
    curr_p, name = info["price"], info["name"]
    mv = shares * curr_p; tot_mv += mv
    tot_exp += (mv * 2 if t.endswith("L") else mv)
    cost = calc_cost_profit(t, shares, d["cost"]/shares)
    tax = mv * (0.001 if t.startswith("00") else 0.003)
    un_p = round(mv - (mv * 0.001425 * (db["fee_discount"]/10)) - tax - cost)
    stock_unrealized += un_p
    display_stocks.append({"ticker": t, "name": name, "shares": shares, "avg_cost": d["cost"]/shares, "curr_p": curr_p, "mv": mv, "un_p": un_p, "ret": (un_p/cost)*100 if cost>0 else 0})

stock_realized = sum(calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"]) for r in db["realized_records"])

fut_unrealized, fut_exposure = 0, 0
for f in db["futures_records"]:
    cp = db["market_data"].get(f["ticker"], {"price": f["price"]})["price"]
    gross = (cp - f["price"]) * f["direction"] * f["multiplier"] * f["lots"]
    un = round(gross - calc_futures_cost(f["multiplier"], f["price"], f["lots"]) - calc_futures_cost(f["multiplier"], cp, f["lots"]))
    fut_unrealized += un; fut_exposure += (cp * f["multiplier"] * f["lots"])

fut_realized = sum(round((r["sell_price"] - r["buy_price"]) * r["direction"] * r["multiplier"] * r["lots"] - calc_futures_cost(r["multiplier"], r["buy_price"], r["lots"]) - calc_futures_cost(r["multiplier"], r["sell_price"], r["lots"])) for r in db["futures_realized"])

total_assets = float(db["account_balance"]) + tot_mv + float(db["other_assets"]) + (float(db["futures_capital"]) + fut_unrealized + fut_realized) - float(db["pledge_amount"]) - float(db["credit_loan"])
total_profit = stock_unrealized + stock_realized + fut_unrealized + fut_realized
lev_str = f"{(tot_exp + fut_exposure) / total_assets:.2f}x" if total_assets > 0 else "0.00x"
m_ratio = (tot_mv / float(db["pledge_amount"]) * 100) if float(db["pledge_amount"]) > 0 else 0

# --- 🚀 歷史紀錄自動存檔 ---
tz_tw = timezone(timedelta(hours=8))
now_tw = datetime.datetime.now(tz_tw)
if now_tw.hour >= 14:
    t_str = now_tw.strftime('%Y-%m-%d')
    if db["history"].get(t_str, {}).get("assets") != total_assets:
        db["history"][t_str] = {"profit": total_profit, "assets": total_assets}
        save_data(db)

# --- 🚀 UI 介面 ---
st.markdown(f"#### 📅 {now_tw.strftime('%Y/%m/%d')}")
m1, m2, m3 = st.columns(3)
m1.metric("槓桿倍數", lev_str)
m2.metric("維持率", f"{m_ratio:.0f}%")
m3.metric("總曝險", f"${(tot_exp + fut_exposure)/10000:,.0f}萬")

st.divider()

# 按鈕操作列 (手機自動縮放)
c_sp, c_a, c_f, c_set, c_up, c_out = st.columns([1.5, 1, 1, 1, 1, 1], gap="small")
if c_a.button("➕股"): add_stock()
if c_f.button("➕期"): add_futures()
if c_set.button("⚙️"): show_settings()
if c_up.button("🔄"):
    with st.spinner("更新中..."):
        for t in {r["ticker"] for r in db["buy_records"]} | {f["ticker"] for f in db["futures_records"]}:
            p, n = fetch_price(t); db["market_data"][t] = {"price": p, "name": n}
    save_data(db); st.rerun()
if c_out.button("🚪"): cookie_manager.delete("user_email"); st.session_state.clear(); st.rerun()

t1, t2, tf, t3, t4, t5 = st.tabs(["📉庫存", "💰已實現", "⚡期貨", "📈獲利", "📊資產", "⚖️資金"])

with t1:
    if display_stocks:
        df_p = pd.DataFrame(display_stocks)
        fig = px.pie(df_p, values='mv', names='ticker', hole=0.6)
        fig.update_layout(height=280, showlegend=False, margin=dict(t=0, b=0, l=0, r=0))
        fig.add_annotation(text=f"TWD<br>{tot_mv:,.0f}", showarrow=False, font_size=18)
        st.plotly_chart(fig, use_container_width=True)
        for s in display_stocks:
            with st.expander(f"【{s['ticker']}】{s['name']} ｜ ${s['curr_p']:,.1f}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("損益", f"${s['un_p']:,}"); c2.metric("報酬", f"{s['ret']:.1f}%"); c3.metric("市值", f"${s['mv']/10000:,.1f}萬")
                b1, b2 = st.columns(2)
                if b1.button("🔍明細", key=f"d_{s['ticker']}", use_container_width=True): show_details(s['ticker'], s['name'])
                if b2.button("🛒賣出", key=f"s_{s['ticker']}", use_container_width=True): sell_stock(s['ticker'], s['name'])
    else: st.info("無現貨庫存")

with t2:
    if db.get("realized_records"):
        for r in sorted(db["realized_records"], key=lambda x: x["sell_date"], reverse=True):
            p = calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"])
            with st.expander(f"{r['sell_date']} ｜ {r['ticker']} ｜ 損益: ${p:,}"):
                st.write(f"股數: {r['shares']:,} | 均進: {r['buy_price']} | 均出: {r['sell_price']}")
    else: st.info("無賣出紀錄")

with tf:
    st.markdown(f"### ⚡ 權益數: ${float(db['futures_capital']) + fut_unrealized + fut_realized:,.0f}")
    for f in db["futures_records"]:
        cp = db["market_data"].get(f["ticker"], {"price": f["price"]})["price"]
        un = round((cp - f["price"]) * f["direction"] * f["multiplier"] * f["lots"] - calc_futures_cost(f["multiplier"], f["price"], f["lots"]) - calc_futures_cost(f["multiplier"], cp, f["lots"]))
        with st.expander(f"【{f['ticker']}】{f['name']} ｜ {'多' if f['direction']==1 else '空'} {f['lots']}口 ｜ {cp}"):
            c1, c2 = st.columns(2); c1.metric("成本", f"{f['price']}"); c2.metric("淨損益", f"${un:,.0f}")
            e1, c1 = st.columns(2)
            if e1.button("✏️修改", key=f"e_{f['id']}", use_container_width=True): 
                st.info("請手動重新新增或連繫 Reid 開發修改功能")
            if c1.button("🛒平倉", key=f"c_{f['id']}", use_container_width=True): close_fut(f['id'], f['name'], f['lots'], f['direction'])

with t3:
    if db["history"]:
        st.line_chart(pd.DataFrame([{"日期": k, "獲利": v["profit"]} for k, v in db["history"].items()]).set_index("日期"))

with t4:
    if db["history"]:
        st.line_chart(pd.DataFrame([{"日期": k, "資產": v["assets"]} for k, v in db["history"].items()]).set_index("日期"))

with t5:
    st.markdown("#### ⚖️ 資金手動調整")
    c1, c2 = st.columns(2)
    nb = c1.number_input("銀行餘額", value=float(db["account_balance"]))
    nfc = c2.number_input("期貨本金", value=float(db["futures_capital"]))
    np = c1.number_input("質押金額", value=float(db["pledge_amount"]))
    ncl = c2.number_input("信貸金額", value=float(db["credit_loan"]))
    no = st.number_input("其他資產", value=float(db["other_assets"]))
    if st.button("💾 確認更新資料庫", type="primary", use_container_width=True):
        db["account_balance"], db["futures_capital"], db["pledge_amount"], db["credit_loan"], db["other_assets"] = nb, nfc, np, ncl, no
        save_data(db); st.success("已更新！"); time.sleep(1); st.rerun()

st.markdown("<h1 style='text-align: center; color: #003366; font-size: 28px;'>一起發大財 💰</h1>", unsafe_allow_html=True)
