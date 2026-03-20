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
# 🔐 Google 登入防護網 (溫柔等待版)
# ==========================================
def login_ui():
    cookies = cookie_manager.get_all()
    if cookies is None:
        st.info("🔄 正在讀取您的安全憑證，請稍候...")
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
            time.sleep(1) 
            st.rerun()
            return True
        except Exception as e:
            st.error("登入失敗或授權碼已過期，請重新嘗試。")
            st.query_params.clear()

    st.markdown("<h1 style='text-align: center; color: #003366; margin-top: 50px;'>🛋️ 個人資產紀錄網</h1>", unsafe_allow_html=True)
    st.write("")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.info("💡 這是一個專屬的私人資產管理系統，請使用 Google 帳號登入，系統會自動載入您個人的專屬資料庫。")
        try:
            res = supabase.auth.sign_in_with_oauth({
                "provider": "google",
                "options": {
                    "redirect_to": "https://reid-stock.streamlit.app/"
                }
            })
            st.link_button("🚀 用 Google 帳號安全登入", res.url, type="primary", use_container_width=True)
        except Exception as e:
            st.error(f"無法產生登入連結: {e}")
    return False

if not login_ui():
    st.stop()

# ==========================================
# 🗄️ 專屬資料庫讀寫邏輯
# ==========================================
user_email = st.session_state["user_email"]

def load_data():
    try:
        response = supabase.table("user_data").select("*").eq("email", user_email).execute()
        if len(response.data) == 0:
            default_db = {
                "fee_discount": 6.0, "pledge_amount": 0.0, "account_balance": 0.0, 
                "credit_loan": 0.0, "other_assets": 0.0, "buy_records": [], "realized_records": [], 
                "history": {}, "market_data": {}, 
                "futures_capital": 0.0, "futures_records": [], "futures_realized": [],
                "fee_fut_tx": 50.0, "fee_fut_mtx": 25.0, "fee_fut_tmf": 10.0, "fee_fut_stf": 20.0
            }
            supabase.table("user_data").insert({"email": user_email, "data": default_db}).execute()
            return default_db
        else:
            return response.data[0]["data"]
    except Exception as e:
        st.error(f"資料庫連線異常: {e}")
        return {}

def save_data(data):
    try:
        supabase.table("user_data").update({"data": data}).eq("email", user_email).execute()
    except Exception as e:
        st.error(f"存檔失敗: {e}")

if "db" not in st.session_state:
    st.session_state.db = load_data()

db = st.session_state.db

# 🚀 防呆補齊抽屜
if "market_data" not in db: db["market_data"] = {}
if "futures_capital" not in db: db["futures_capital"] = 0.0
if "futures_records" not in db: db["futures_records"] = []
if "futures_realized" not in db: db["futures_realized"] = []
if "fee_fut_tx" not in db: db["fee_fut_tx"] = 50.0
if "fee_fut_mtx" not in db: db["fee_fut_mtx"] = 25.0
if "fee_fut_tmf" not in db: db["fee_fut_tmf"] = 10.0
if "fee_fut_stf" not in db: db["fee_fut_stf"] = 20.0

# --- 🚀 核心計算與雙棲爬蟲 ---
def fetch_price(ticker):
    price = 0.0
    name = ticker
    t_lower = ticker.lower()
    urls_to_try = [
        (f"https://www.wantgoo.com/stock/{t_lower}", 'span'),
        (f"https://www.wantgoo.com/futures/{t_lower}", 'div')
    ]
    for url, tag in urls_to_try:
        try:
            resp_w = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            if resp_w.status_code == 200:
                soup_w = BeautifulSoup(resp_w.text, 'html.parser')
                deal_node = soup_w.find(tag, class_='deal', attrs={'c-model': 'close'})
                if deal_node and deal_node.text.strip() != "--":
                    price = float(deal_node.text.replace(',', ''))
                    name_h3 = soup_w.find('h3', attrs={'c-model': 'name'})
                    if name_h3 and name_h3.text.strip():
                        name = name_h3.text.strip()
                    break 
        except: pass
    if price == 0.0:
        for exchange in ['TPE', 'TWO']:
            if price > 0: break
            try:
                url_g = f"https://www.google.com/finance/quote/{ticker}:{exchange}?hl=zh-TW"
                resp_g = requests.get(url_g, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                soup_g = BeautifulSoup(resp_g.text, 'html.parser')
                p_div = soup_g.find('div', class_='YMlKec fxKbKc')
                if p_div: price = float(p_div.text.replace('$', '').replace(',', ''))
            except: pass
    if price == 0.0 or name == ticker:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{ticker}"
            resp_y = requests.get(url_y, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            soup_y = BeautifulSoup(resp_y.text, 'html.parser')
            if name == ticker:
                title_tag = soup_y.find('title')
                if title_tag:
                    extracted_name = title_tag.text.split('(')[0].strip()
                    if "Yahoo" not in extracted_name: name = extracted_name
            if price == 0.0:
                match = re.search(r'"regularMarketPrice":([0-9.]+)', resp_y.text)
                if match: price = float(match.group(1))
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

# --- 彈出視窗 (Dialogs) ---
@st.dialog("⚙️ 全域設定")
def show_settings_dialog():
    st.markdown("#### 📈 現貨設定")
    new_disc = st.number_input("股票手續費折數", value=float(db.get("fee_discount", 6.0)), step=0.1)
    st.markdown("#### ⚡ 期貨單邊手續費 (元/口)")
    c1, c2 = st.columns(2)
    new_fee_tx = c1.number_input("大台", value=float(db.get("fee_fut_tx", 50.0)))
    new_fee_mtx = c2.number_input("小台", value=float(db.get("fee_fut_mtx", 25.0)))
    if st.button("💾 儲存設定", type="primary", use_container_width=True):
        db["fee_discount"], db["fee_fut_tx"], db["fee_fut_mtx"] = new_disc, new_fee_tx, new_fee_mtx
        save_data(db); st.rerun()

@st.dialog("➕ 新增現貨股票")
def show_add_stock_dialog():
    in_date, in_ticker = st.date_input("買進日期"), st.text_input("股票代號").upper()
    in_shares, in_price = st.number_input("買進股數", min_value=1, step=1000), st.number_input("買進單價", min_value=0.01)
    if st.button("確認新增", type="primary", use_container_width=True):
        if in_ticker:
            p, n = fetch_price(in_ticker)
            db["market_data"][in_ticker] = {"price": p, "name": n}
            db["buy_records"].append({"id": int(time.time()), "date": str(in_date), "ticker": in_ticker, "shares": in_shares, "price": in_price})
            save_data(db); st.rerun()

@st.dialog("⚡ 新增期貨部位")
def show_add_futures_dialog():
    f_date = st.date_input("建立日期")
    f_ticker = st.text_input("商品代號", placeholder="提示：期貨代號前請加 W (例如 WCDFJ6)").upper()
    f_dir = 1 if "多" in st.selectbox("多空方向", ["做多 (+1)", "做空 (-1)"]) else -1
    mult_str = st.selectbox("契約規格", ["大台 (200)", "小台 (50)", "微台 (10)", "股票期貨 (2000)", "小型股期 (100)", "自訂"])
    f_mult = int(re.search(r'\((\d+)\)', mult_str).group(1)) if "(" in mult_str else st.number_input("自訂乘數", min_value=1)
    f_lots, f_price = st.number_input("口數", min_value=1), st.number_input("成交價格", min_value=0.01)
    if st.button("確認新增期貨", type="primary", use_container_width=True):
        if f_ticker:
            with st.spinner("抓取名稱中..."):
                p, n = fetch_price(f_ticker)
                final_name = n if n != f_ticker else f_ticker
            db["futures_records"].append({"id": int(time.time()), "date": str(f_date), "ticker": f_ticker, "name": final_name, "direction": f_dir, "multiplier": f_mult, "lots": f_lots, "price": f_price})
            db["market_data"][f_ticker] = {"price": p if p > 0 else f_price, "name": final_name}
            save_data(db); st.rerun()

@st.dialog("✏️ 修改期貨成本")
def show_edit_futures_cost_dialog(f_id, f_name, current_cost):
    new_cost = st.number_input(f"修改 {f_name} 成交價", value=float(current_cost))
    if st.button("確認修改", type="primary"):
        for r in db["futures_records"]:
            if r["id"] == f_id: r["price"] = new_cost; break
        save_data(db); st.rerun()

@st.dialog("🛒 平倉期貨")
def show_close_futures_dialog(f_id, f_name, f_lots, f_dir):
    sell_date, sell_lots = st.date_input("平倉日期"), st.number_input("口數", min_value=1, max_value=f_lots)
    sell_price = st.number_input("平倉價格", min_value=0.01)
    if st.button("確認平倉", type="primary"):
        for r in db["futures_records"]:
            if r["id"] == f_id:
                db["futures_realized"].append({"sell_date": str(sell_date), "ticker": r["ticker"], "name": r["name"], "direction": r["direction"], "multiplier": r["multiplier"], "lots": sell_lots, "buy_price": r["price"], "sell_price": sell_price})
                r["lots"] -= sell_lots; break
        db["futures_records"] = [r for r in db["futures_records"] if r["lots"] > 0]
        save_data(db); st.rerun()

@st.dialog("🔍 股票明細")
def show_details_dialog(ticker, name):
    recs = [r for r in db.get("buy_records", []) if r["ticker"] == ticker]
    for r in recs:
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        c1.write(r["date"]); c2.write(f"{r['shares']:,}"); c3.write(f"${r['price']:.2f}")
        if c4.button("🗑️", key=f"del_{r['id']}"):
            db["buy_records"] = [x for x in db["buy_records"] if x["id"] != r["id"]]
            save_data(db); st.rerun()

@st.dialog("🛒 賣出股票")
def show_sell_dialog(ticker, name):
    tot_s = sum(r["shares"] for r in db["buy_records"] if r["ticker"] == ticker)
    sell_date, sell_shares = st.date_input("賣出日期"), st.number_input("股數", min_value=1, max_value=tot_s)
    sell_price = st.number_input("單價", value=float(db["market_data"].get(ticker, {"price": 0.0})["price"]))
    if st.button("確認賣出", type="primary"):
        rem = sell_shares
        for r in sorted([x for x in db["buy_records"] if x["ticker"] == ticker], key=lambda x: x["date"]):
            if rem <= 0: break
            take = min(r["shares"], rem)
            db["realized_records"].append({"sell_date": str(sell_date), "ticker": ticker, "shares": take, "buy_price": r["price"], "sell_price": sell_price})
            r["shares"] -= take; rem -= take
        db["buy_records"] = [x for x in db["buy_records"] if x["shares"] > 0]
        save_data(db); st.rerun()

# --- 計算邏輯 ---
agg = {}
for r in db["buy_records"]:
    t = r["ticker"]
    if t not in agg: agg[t] = {"shares": 0, "cost": 0}
    agg[t]["shares"] += r["shares"]; agg[t]["cost"] += r["shares"] * r["price"]

tot_exp, tot_mv, stock_unrealized, display_data = 0, 0, 0, []
for t, d in agg.items():
    shares = d["shares"]
    info = db["market_data"].get(t, {"price": 0.0, "name": t})
    curr_p, name = info["price"], info["name"]
    mv = shares * curr_p; tot_mv += mv
    tot_exp += (mv * 2 if t.endswith("L") else mv)
    cost = calc_cost_profit(t, shares, d["cost"]/shares)
    net_v = mv - (mv * 0.001425 * (db["fee_discount"]/10)) - (mv * (0.001 if t.startswith("00") else 0.003))
    un_profit = round(net_v - cost); stock_unrealized += un_profit
    display_data.append({"ticker": t, "name": name, "shares": shares, "avg_cost": d["cost"]/shares, "curr_p": curr_p, "mv": mv, "un_profit": un_profit, "ret_rate": (un_profit/cost)*100 if cost>0 else 0})

stock_realized = sum(calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"]) for r in db["realized_records"])
futures_unrealized, futures_exposure = 0, 0
for f in db["futures_records"]:
    curr_p = db["market_data"].get(f["ticker"], {"price": f["price"]})["price"]
    gross = (curr_p - f["price"]) * f["direction"] * f["multiplier"] * f["lots"]
    un_p = round(gross - calc_futures_cost(f["multiplier"], f["price"], f["lots"]) - calc_futures_cost(f["multiplier"], curr_p, f["lots"]))
    futures_unrealized += un_p; futures_exposure += (curr_p * f["multiplier"] * f["lots"])

futures_realized_p = 0
for r in db["futures_realized"]:
    gross = (r["sell_price"] - r["buy_price"]) * r["direction"] * r["multiplier"] * r["lots"]
    futures_realized_p += round(gross - calc_futures_cost(r["multiplier"], r["buy_price"], r["lots"]) - calc_futures_cost(r["multiplier"], r["sell_price"], r["lots"]))

fut_cap = float(db.get("futures_capital", 0.0))
futures_equity = fut_cap + futures_unrealized + futures_realized_p
tot_profit = stock_unrealized + stock_realized + futures_unrealized + futures_realized_p
acc_bal, oth_assets, pld_amt, crd_loan = float(db.get("account_balance", 0.0)), float(db.get("other_assets", 0.0)), float(db.get("pledge_amount", 0.0)), float(db.get("credit_loan", 0.0))
total_assets = acc_bal + tot_mv + oth_assets + futures_equity - pld_amt - crd_loan
lev_str = f"{(tot_exp + futures_exposure) / total_assets:.2f}x" if total_assets > 0 else "0.00x"

# --- 主畫面 ---
st.markdown(f"#### 📅 {datetime.datetime.now(timezone(timedelta(hours=8))).strftime('%Y/%m/%d')}")
m1, m2 = st.columns(2)
m1.metric("總淨資產", f"${total_assets:,.0f}"); m2.metric("總獲利", f"${tot_profit:,.0f}")
st.divider()

tab1, tab2, tab_f, tab3, tab4, tab5 = st.tabs(["📉 股票庫存", "💰 股票已實現", "⚡ 期貨庫存", "📈 獲利走勢", "📊 資產走勢", "⚖️ 資金控管"])

with tab1:
    if display_data:
        # 🚀 甜甜圈圖 (防噴版)
        df_pie = pd.DataFrame([{"Stock": f"{i['ticker']} {i['name']}", "Value": i['mv']} for i in display_data if i['mv'] > 0])
        if not df_pie.empty:
            fig = px.pie(df_pie, values='Value', names='Stock', hole=0.6)
            fig.update_layout(height=350, showlegend=True)
            fig.add_annotation(text=f"TWD<br>{tot_mv:,.0f}", showarrow=False, font_size=20)
            st.plotly_chart(fig, use_container_width=True)
        for item in display_data:
            with st.expander(f"【{item['ticker']}】{item['name']} ｜ ${item['curr_p']:,.2f}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("市值", f"${item['mv']:,.0f}"); c2.metric("損益", f"${item['un_profit']:,}"); c3.metric("報酬", f"{item['ret_rate']:.2f}%")
                b1, b2 = st.columns(2)
                if b1.button("🔍 明細", key=f"d_{item['ticker']}", use_container_width=True): show_details_dialog(item['ticker'], item['name'])
                if b2.button("🛒 賣出", key=f"s_{item['ticker']}", use_container_width=True): show_sell_dialog(item['ticker'], item['name'])
    else: st.info("無現貨庫存。")

with tab_f:
    st.markdown(f"### ⚡ 總權益數: ${futures_equity:,.0f}")
    if db["futures_records"]:
        for f in db["futures_records"]:
            cp = db["market_data"].get(f["ticker"], {"price": f["price"]})["price"]
            un = round((cp - f["price"]) * f["direction"] * f["multiplier"] * f["lots"] - calc_futures_cost(f["multiplier"], f["price"], f["lots"]) - calc_futures_cost(f["multiplier"], cp, f["lots"]))
            with st.expander(f"【{f['ticker']}】{f['name']} ｜ {'多' if f['direction']==1 else '空'} {f['lots']}口 ｜ 現價: {cp}"):
                c1, c2 = st.columns(2); c1.metric("成本", f"{f['price']}"); c2.metric("損益", f"${un:,.0f}")
                _, e1, c1 = st.columns([2, 1, 1])
                if e1.button("✏️ 修改", key=f"e_{f['id']}", use_container_width=True): show_edit_futures_cost_dialog(f['id'], f['name'], f['price'])
                if c1.button("🛒 平倉", key=f"c_{f['id']}", use_container_width=True): show_close_futures_dialog(f['id'], f['name'], f['lots'], f['direction'])
    else: st.info("無期貨部位。")

with tab5:
    st.markdown("#### 🛡️ 風險指標")
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("槓桿倍數", lev_str); rc2.metric("質押維持率", f"{m_ratio:.1f}%"); rc3.metric("期貨曝險", f"${futures_exposure:,.0f}")
    st.divider()
    ec1, ec2, ec3, ec4, ec5 = st.columns(5)
    nb = ec1.number_input("銀行餘額", value=int(acc_bal)); nfc = ec2.number_input("期貨本金", value=int(fut_cap)); no = ec3.number_input("其他資產", value=int(oth_assets)); np = ec4.number_input("質押金額", value=int(pld_amt)); nc = ec5.number_input("信貸金額", value=int(crd_loan))
    if st.button("💾 更新數據", type="primary"):
        db["account_balance"], db["futures_capital"], db["other_assets"], db["pledge_amount"], db["credit_loan"] = nb, nfc, no, np, nc
        save_data(db); st.rerun()

st.markdown("<h1 style='text-align: center; color: #003366; font-style: italic;'>一起發大財 💰</h1>", unsafe_allow_html=True)
