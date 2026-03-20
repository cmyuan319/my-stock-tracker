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

# 🚀 確保所有用戶都有期貨與手續費的欄位
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
        except:
            pass

    if price == 0.0:
        for exchange in ['TPE', 'TWO']:
            if price > 0: break
            try:
                url_g = f"https://www.google.com/finance/quote/{ticker}:{exchange}?hl=zh-TW"
                resp_g = requests.get(url_g, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                soup_g = BeautifulSoup(resp_g.text, 'html.parser')
                p_div = soup_g.find('div', class_='YMlKec fxKbKc')
                if p_div: 
                    price = float(p_div.text.replace('$', '').replace(',', ''))
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

# 🚀 新增：期貨手續費與期交稅計算函數
def calc_futures_cost(multiplier, price, lots):
    if multiplier == 200: fee = float(db.get("fee_fut_tx", 50.0))
    elif multiplier == 50: fee = float(db.get("fee_fut_mtx", 25.0))
    elif multiplier == 10: fee = float(db.get("fee_fut_tmf", 10.0))
    elif multiplier in [100, 2000]: fee = float(db.get("fee_fut_stf", 20.0))
    else: fee = float(db.get("fee_fut_tx", 50.0)) # 自訂乘數預設以大台計價
    
    # 台灣期交稅率約為十萬分之二 (0.00002)
    tax = price * multiplier * lots * 0.00002
    return (fee * lots) + tax

# --- 彈出視窗 (Dialogs) ---
@st.dialog("⚙️ 全域設定")
def show_settings_dialog():
    st.markdown("#### 📈 現貨設定")
    new_disc = st.number_input("股票手續費折數", value=float(db.get("fee_discount", 6.0)), step=0.1)
    
    st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
    st.markdown("#### ⚡ 期貨單邊手續費設定 (元/口)")
    c1, c2 = st.columns(2)
    new_fee_tx = c1.number_input("大台 (TX)", value=float(db.get("fee_fut_tx", 50.0)), step=1.0)
    new_fee_mtx = c2.number_input("小台 (MTX)", value=float(db.get("fee_fut_mtx", 25.0)), step=1.0)
    new_fee_tmf = c1.number_input("微台 (TMF)", value=float(db.get("fee_fut_tmf", 10.0)), step=1.0)
    new_fee_stf = c2.number_input("股票期貨 (STF)", value=float(db.get("fee_fut_stf", 20.0)), step=1.0)

    if st.button("💾 儲存設定", type="primary", use_container_width=True):
        db["fee_discount"] = new_disc
        db["fee_fut_tx"] = new_fee_tx
        db["fee_fut_mtx"] = new_fee_mtx
        db["fee_fut_tmf"] = new_fee_tmf
        db["fee_fut_stf"] = new_fee_stf
        save_data(db)
        st.success("設定已更新！")
        time.sleep(1)
        st.rerun()

@st.dialog("➕ 新增現貨股票")
def show_add_stock_dialog():
    in_date = st.date_input("買進日期")
    in_ticker = st.text_input("股票代號").upper()
    in_shares = st.number_input("買進股數", min_value=1, step=1000)
    in_price = st.number_input("買進單價", min_value=0.01, step=1.0)
    if st.button("確認新增", type="primary", use_container_width=True):
        if in_ticker:
            if in_ticker not in db["market_data"]:
                p, n = fetch_price(in_ticker)
                db["market_data"][in_ticker] = {"price": p, "name": n}
                
            next_id = max([r.get("id", 0) for r in db.get("buy_records", [])] + [0]) + 1
            db["buy_records"].append({
                "id": next_id, "date": str(in_date), "ticker": in_ticker, 
                "shares": in_shares, "price": in_price
            })
            save_data(db)
            st.success(f"已新增 {in_ticker}！")
            time.sleep(1)
            st.rerun()

@st.dialog("⚡ 新增期貨部位")
def show_add_futures_dialog():
    f_date = st.date_input("建立日期")
    f_ticker = st.text_input("商品代號", placeholder="提示：期貨代號前請加 W (例如 WCDFJ6)").upper()
    
    f_dir_str = st.selectbox("多空方向", ["做多 (+1)", "做空 (-1)"])
    f_dir = 1 if "多" in f_dir_str else -1
    
    mult_str = st.selectbox("契約規格 (乘數)", [
        "大台 (200)", "小台 (50)", "微台 (10)", "股票期貨 (2000)", "小型股期 (100)", "自訂"
    ])
    if mult_str == "自訂":
        f_mult = st.number_input("自訂乘數", min_value=1, value=1)
    else:
        f_mult = int(re.search(r'\((\d+)\)', mult_str).group(1))
        
    f_lots = st.number_input("口數", min_value=1, step=1)
    f_price = st.number_input("成交價格 (點數/元)", min_value=0.01, step=1.0)
    
    if st.button("確認新增期貨", type="primary", use_container_width=True):
        if f_ticker:
            with st.spinner("雷達掃描商品名稱中..."):
                p, n = fetch_price(f_ticker)
                final_name = n if (n and n != f_ticker) else f_ticker 
                
            next_id = max([r.get("id", 0) for r in db.get("futures_records", [])] + [0]) + 1
            db["futures_records"].append({
                "id": next_id, "date": str(f_date), "ticker": f_ticker, "name": final_name,
                "direction": f_dir, "multiplier": f_mult, "lots": f_lots, "price": f_price
            })
            
            if f_ticker not in db["market_data"]:
                db["market_data"][f_ticker] = {"price": p if p > 0 else f_price, "name": final_name}
            save_data(db)
            st.success(f"已成功新增部位 {final_name}！")
            time.sleep(1)
            st.rerun()

@st.dialog("✏️ 修改期貨成本價")
def show_edit_futures_cost_dialog(f_id, f_name, current_cost):
    st.markdown(f"### 修改 {f_name} 成本")
    new_cost = st.number_input("新的成交價/成本價", value=float(current_cost), min_value=0.01, step=1.0)
    
    if st.button("確認修改", type="primary", use_container_width=True):
        for r in db["futures_records"]:
            if r["id"] == f_id:
                r["price"] = new_cost
                break
        save_data(db)
        st.success("成本價已成功更新！")
        time.sleep(1)
        st.rerun()

@st.dialog("🛒 平倉期貨")
def show_close_futures_dialog(f_id, f_name, f_lots, f_dir):
    st.markdown(f"### 平倉 {f_name}")
    st.info(f"目前持有部位: **{f_lots}** 口 ({'做多' if f_dir==1 else '做空'})")
    sell_date = st.date_input("平倉日期")
    sell_lots = st.number_input("平倉口數", min_value=1, max_value=f_lots, step=1)
    sell_price = st.number_input("平倉價格 (點數/元)", min_value=0.01, step=1.0)
    
    if st.button("確認平倉", type="primary", use_container_width=True):
        for r in db["futures_records"]:
            if r["id"] == f_id:
                db["futures_realized"].append({
                    "sell_date": str(sell_date), "ticker": r["ticker"], "name": r["name"],
                    "direction": r["direction"], "multiplier": r["multiplier"], 
                    "lots": sell_lots, "buy_price": r["price"], "sell_price": sell_price
                })
                r["lots"] -= sell_lots
                break
        
        db["futures_records"] = [r for r in db["futures_records"] if r["lots"] > 0]
        save_data(db)
        st.success(f"已成功平倉 {sell_lots} 口！")
        time.sleep(1)
        st.rerun()

@st.dialog("🔍 逐筆買進明細與管理")
def show_details_dialog(ticker, name):
    st.markdown(f"### {ticker} {name}")
    records = sorted([r for r in db.get("buy_records", []) if r["ticker"] == ticker], key=lambda x: x["date"], reverse=True)
    if not records:
        st.warning("目前無庫存紀錄。")
        return
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    c1.write("**日期**")
    c2.write("**股數**")
    c3.write("**單價**")
    c4.write("**刪除**")
    st.divider()
    for r in records:
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        c1.write(r["date"])
        c2.write(f"{r['shares']:,}")
        c3.write(f"${r['price']:.2f}")
        if c4.button("🗑️", key=f"del_{r['id']}"):
            db["buy_records"] = [rec for rec in db["buy_records"] if rec["id"] != r["id"]]
            save_data(db)
            st.rerun()

@st.dialog("🛒 賣出股票")
def show_sell_dialog(ticker, name):
    st.markdown(f"### 賣出 {ticker} {name}")
    tot_s = sum(r["shares"] for r in db.get("buy_records", []) if r["ticker"] == ticker)
    st.info(f"目前總庫存: **{tot_s:,}** 股")
    sell_date = st.date_input("賣出日期")
    sell_shares = st.number_input("賣出股數", min_value=1, max_value=tot_s, step=1000)
    
    current_p = db.get("market_data", {}).get(ticker, {"price": 0.0})["price"]
    sell_price = st.number_input("賣出單價", value=float(current_p), min_value=0.01, step=1.0)
    
    if st.button("確認賣出", type="primary", use_container_width=True):
        rem = sell_shares
        target_records = sorted([r for r in db.get("buy_records", []) if r["ticker"] == ticker], key=lambda x: x["date"])
        for r in target_records:
            if rem <= 0: break
            take = min(r["shares"], rem)
            db["realized_records"].append({
                "sell_date": str(sell_date), "ticker": ticker, 
                "shares": take, "buy_price": r["price"], "sell_price": sell_price
            })
            r["shares"] -= take
            rem -= take
        db["buy_records"] = [r for r in db["buy_records"] if r["shares"] > 0]
        save_data(db)
        st.success(f"已成功賣出 {sell_shares} 股！")
        time.sleep(1)
        st.rerun()

# --- 頂部操作列 ---
col_space, col_add_s, col_add_f, col_set, col_update, col_out = st.columns([4, 1, 1, 1, 1, 1])
with col_add_s:
    if st.button("➕ 股", help="新增現貨股票", use_container_width=True): show_add_stock_dialog()
with col_add_f:
    if st.button("➕ 期", help="新增期貨合約", use_container_width=True): show_add_futures_dialog()
with col_set:
    if st.button("⚙️", help="設定", use_container_width=True): show_settings_dialog()
with col_update:
    if st.button("🔄", help="自動更新最新股價", use_container_width=True):
        with st.spinner("雙棲雷達掃描中..."):
            unique_tickers = set([r["ticker"] for r in db.get("buy_records", [])] + [r["ticker"] for r in db.get("realized_records", [])])
            fut_tickers = set([r["ticker"] for r in db.get("futures_records", [])])
            for t in unique_tickers.union(fut_tickers):
                p, n = fetch_price(t)
                if p > 0: 
                    db["market_data"][t] = {"price": p, "name": n}
            save_data(db)
        st.success("報價更新完成！")
        time.sleep(0.5)
        st.rerun()
with col_out:
    if st.button("🚪", help="登出", use_container_width=True):
        supabase.auth.sign_out()
        st.session_state.clear()
        cookie_manager.delete("user_email") 
        time.sleep(0.5)
        st.rerun()

# --- 現貨數據計算 ---
agg = {}
for r in db.get("buy_records", []):
    t = r["ticker"]
    if t not in agg: agg[t] = {"shares": 0, "cost_basis": 0}
    agg[t]["shares"] += r["shares"]
    agg[t]["cost_basis"] += r["shares"] * r["price"]

tot_exp, tot_mv, stock_unrealized = 0, 0, 0
display_data = []

for t, d in agg.items():
    shares = d["shares"]
    if shares == 0: continue
    avg_cost = d["cost_basis"] / shares
    
    market_info = db.get("market_data", {}).get(t, {"price": 0.0, "name": t})
    curr_p = market_info["price"]
    name = market_info["name"]
    
    mv = shares * curr_p
    tot_mv += mv
    if t.endswith("L"): tot_exp += (mv * 2)
    else: tot_exp += mv
        
    cost = calc_cost_profit(t, shares, avg_cost)
    tax_rate = 0.001 if t.startswith("00") else 0.003
    sell_fee = mv * 0.001425 * (db.get("fee_discount", 6.0) / 10.0)
    net_v = mv - sell_fee - (mv * tax_rate)
    un_profit = round(net_v - cost)
    stock_unrealized += un_profit
    ret_rate = (un_profit / cost) * 100 if cost > 0 else 0
    
    display_data.append({
        "ticker": t, "name": name, "shares": shares, "avg_cost": avg_cost, 
        "curr_p": curr_p, "mv": mv, "un_profit": un_profit, "ret_rate": ret_rate
    })

stock_realized = sum(calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"]) for r in db.get("realized_records", []))

# --- 🚀 期貨數據精算 (含手續費與稅金) ---
futures_unrealized = 0
futures_exposure = 0
for f in db.get("futures_records", []):
    curr_p = db.get("market_data", {}).get(f["ticker"], {"price": f["price"]})["price"]
    
    # 毛利
    gross_profit = (curr_p - f["price"]) * f["direction"] * f["multiplier"] * f["lots"]
    
    # 扣除一進一出的交易成本
    open_cost = calc_futures_cost(f["multiplier"], f["price"], f["lots"])
    close_cost_est = calc_futures_cost(f["multiplier"], curr_p, f["lots"])
    un_profit = round(gross_profit - open_cost - close_cost_est)
    
    futures_unrealized += un_profit
    
    # 曝險為絕對值 (合約價值)
    exp = curr_p * f["multiplier"] * f["lots"]
    futures_exposure += exp

futures_realized_profit = 0
for r in db.get("futures_realized", []):
    gross_profit = (r["sell_price"] - r["buy_price"]) * r["direction"] * r["multiplier"] * r["lots"]
    open_cost = calc_futures_cost(r["multiplier"], r["buy_price"], r["lots"])
    close_cost = calc_futures_cost(r["multiplier"], r["sell_price"], r["lots"])
    profit = round(gross_profit - open_cost - close_cost)
    futures_realized_profit += profit

fut_cap = float(db.get("futures_capital", 0.0))
# 期貨權益數 = 投入本金 + 所有稅後淨損益
futures_equity = fut_cap + futures_unrealized + futures_realized_profit

# --- 總資金與指標 ---
tot_profit = stock_unrealized + stock_realized + futures_unrealized + futures_realized_profit

acc_bal = float(db.get("account_balance", 0.0))
oth_assets = float(db.get("other_assets", 0.0))
pld_amt = float(db.get("pledge_amount", 0.0))
crd_loan = float(db.get("credit_loan", 0.0))

# 總淨資產 (NAV)
total_assets = acc_bal + tot_mv + oth_assets + futures_equity - pld_amt - crd_loan

# 總曝險與槓桿倍數 (正確版：分子不含借貸金額)
lev_numerator = tot_exp + futures_exposure
if total_assets > 0: 
    lev_str = f"{lev_numerator / total_assets:.2f}x"
elif total_assets <= 0 and lev_numerator > 0: 
    lev_str = "∞"
else: 
    lev_str = "0.0x"

m_ratio = (tot_mv / pld_amt * 100) if pld_amt > 0 else 0

# --- 🚀 每日 14:00 後自動記錄歷史邏輯 ---
tz_tw = timezone(timedelta(hours=8))
now_tw = datetime.datetime.now(tz_tw)
today_str = now_tw.strftime('%Y-%m-%d')

if "history" not in db: db["history"] = {}
for k, v in db["history"].items():
    if isinstance(v, (int, float)): db["history"][k] = {"profit": v, "assets": total_assets}

if now_tw.hour >= 14:
    current_history = db["history"].get(today_str, {})
    if current_history.get("profit") != tot_profit or current_history.get("assets") != total_assets:
        db["history"][today_str] = {"profit": tot_profit, "assets": total_assets}
        save_data(db)

# --- 主畫面：極簡大看板 ---
st.markdown(f"#### 📅 {now_tw.strftime('%Y/%m/%d')}")
m1, m2 = st.columns(2)
m1.metric("總淨資產", f"${total_assets:,.0f}")
m2.metric("總獲利", f"${tot_profit:,.0f}")

st.divider()

# --- 六大分頁 ---
tab1, tab2, tab_futures, tab3, tab4, tab5 = st.tabs(["📉 股票庫存", "💰 股票已實現", "⚡ 期貨庫存", "📈 獲利走勢", "📊 資產走勢", "⚖️ 資金控管"])

with tab1:
    if display_data:
        for item in display_data:
            card_title = f"【{item['ticker']}】{item['name']} ｜ 現價: ${item['curr_p']:,.2f}"
            with st.expander(card_title):
                c1, c2, c3 = st.columns(3)
                c1.metric("總股數", f"{item['shares']:,}")
                c2.metric("均價", f"${item['avg_cost']:.2f}")
                c3.metric("現價", f"${item['curr_p']:.2f}")
                
                c4, c5, c6 = st.columns(3)
                c4.metric("目前市值", f"${round(item['mv']):,}")
                c5.metric("未實現損益", f"${item['un_profit']:,}")
                c6.metric("報酬率", f"{item['ret_rate']:.2f}%")
                
                st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
                btn1, btn2 = st.columns(2)
                if btn1.button("🔍 明細", key=f"d_{item['ticker']}", use_container_width=True): show_details_dialog(item['ticker'], item['name'])
                if btn2.button("🛒 賣出", key=f"s_{item['ticker']}", use_container_width=True): show_sell_dialog(item['ticker'], item['name'])
    else:
        st.info("目前沒有未實現的現貨庫存。")

with tab2:
    if db.get("realized_records"):
        for r in sorted(db["realized_records"], key=lambda x: x["sell_date"], reverse=True):
            p = calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"])
            name = db.get("market_data", {}).get(r["ticker"], {"name": r["ticker"]})["name"]
            card_title = f"{r['sell_date']} ｜ {r['ticker']} {name} ｜ 損益: ${p:,}"
            with st.expander(card_title):
                c1, c2, c3 = st.columns(3)
                c1.metric("交易股數", f"{r['shares']:,}")
                c2.metric("買進價格", f"${r['buy_price']:.2f}")
                c3.metric("賣出價格", f"${r['sell_price']:.2f}")
    else:
        st.info("目前還沒有賣出紀錄。")

with tab_futures:
    st.markdown(f"### ⚡ 總權益數: ${futures_equity:,.0f}")
    c1, c2, c3 = st.columns(3)
    c1.metric("投入本金", f"${fut_cap:,.0f}")
    c2.metric("淨未實現損益", f"${futures_unrealized:,.0f}")
    c3.metric("淨已實現損益", f"${futures_realized_profit:,.0f}")
    
    st.markdown("#### 未平倉部位")
    if db.get("futures_records"):
        for f in db["futures_records"]:
            curr_p = db.get("market_data", {}).get(f["ticker"], {"price": f["price"]})["price"]
            
            gross = (curr_p - f["price"]) * f["direction"] * f["multiplier"] * f["lots"]
            open_cost = calc_futures_cost(f["multiplier"], f["price"], f["lots"])
            close_cost_est = calc_futures_cost(f["multiplier"], curr_p, f["lots"])
            un_profit = round(gross - open_cost - close_cost_est)
            
            dir_str = "🔴 多" if f["direction"] == 1 else "🟢 空"
            
            with st.expander(f"【{f['ticker']}】{f['name']} ｜ {dir_str} {f['lots']}口 ｜ 現價: {curr_p}"):
                fc1, fc2, fc3, fc4 = st.columns(4)
                fc1.metric("成交價", f"{f['price']}")
                fc2.metric("現價", f"{curr_p}")
                fc3.metric("契約乘數", f"{f['multiplier']}")
                fc4.metric("淨損益(含手續費/稅)", f"${un_profit:,.0f}")
                
                st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
                _, btn_edit, btn_close = st.columns([2, 1, 1])
                if btn_edit.button("✏️ 修改成本", key=f"btn_e_{f['id']}", use_container_width=True):
                    show_edit_futures_cost_dialog(f['id'], f['name'], f['price'])
                if btn_close.button("🛒 平倉", key=f"btn_c_{f['id']}", use_container_width=True):
                    show_close_futures_dialog(f['id'], f['name'], f['lots'], f['direction'])
    else:
        st.info("目前沒有未平倉的期貨部位。")
        
    st.divider()
    st.markdown("#### 已實現紀錄")
    if db.get("futures_realized"):
        for r in sorted(db["futures_realized"], key=lambda x: x["sell_date"], reverse=True):
            gross_profit = (r["sell_price"] - r["buy_price"]) * r["direction"] * r["multiplier"] * r["lots"]
            open_cost = calc_futures_cost(r["multiplier"], r["buy_price"], r["lots"])
            close_cost = calc_futures_cost(r["multiplier"], r["sell_price"], r["lots"])
            net_profit = round(gross_profit - open_cost - close_cost)
            
            dir_str = "多" if r["direction"] == 1 else "空"
            with st.expander(f"{r['sell_date']} ｜ {r['name']} ({dir_str}) {r['lots']}口 ｜ 淨損益: ${net_profit:,.0f}"):
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("進場價", f"{r['buy_price']}")
                rc2.metric("出場價", f"{r['sell_price']}")
                rc3.metric("乘數", f"{r['multiplier']}")
    else:
        st.write("尚無已實現紀錄。")

with tab3:
    st.markdown("### 📈 每日總獲利走勢")
    if db.get("history"):
        df_profit = pd.DataFrame([{"日期": k, "總獲利": v["profit"]} for k, v in db["history"].items()])
        st.line_chart(df_profit.set_index("日期"))
    else:
        st.info("系統會從今天 14:00 開始自動幫你記錄！")

with tab4:
    st.markdown("### 📊 每日總資產走勢")
    if db.get("history"):
        df_assets = pd.DataFrame([{"日期": k, "總資產": v["assets"]} for k, v in db["history"].items()])
        st.line_chart(df_assets.set_index("日期"))
    else:
        st.info("系統會從今天 14:00 開始自動幫你記錄！")

with tab5:
    st.markdown("#### 🛡️ 風險與獲利指標")
    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("股票總曝險", f"${tot_exp:,.0f}")
    rc2.metric("期貨總曝險", f"${futures_exposure:,.0f}")
    rc3.metric("總槓桿倍數", lev_str)
    rc4.metric("質押維持率", f"{m_ratio:.1f}%")
    
    st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)
    
    st.markdown("#### 💵 資金編輯區")
    ec1, ec2, ec3, ec4, ec5 = st.columns(5)
    new_bal = ec1.number_input("銀行帳戶餘額", value=int(acc_bal), step=10000)
    new_fut_cap = ec2.number_input("期貨投入本金", value=int(fut_cap), step=10000)
    new_oth = ec3.number_input("其他資產", value=int(oth_assets), step=10000)
    new_pld = ec4.number_input("質押金額", value=int(pld_amt), step=10000)
    new_crd = ec5.number_input("信貸金額", value=int(crd_loan), step=10000)
    
    if st.button("💾 更新資金數據", type="primary"):
        db["account_balance"] = float(new_bal)
        db["futures_capital"] = float(new_fut_cap)
        db["other_assets"] = float(new_oth)
        db["pledge_amount"] = float(new_pld)
        db["credit_loan"] = float(new_crd)
        save_data(db)
        st.success("資金數據已更新！")
        time.sleep(1)
        st.rerun()

st.write("") 
st.markdown("<h1 style='text-align: center; color: #003366; font-style: italic; font-weight: bold; font-size: 36px;'>一起發大財 💰</h1>", unsafe_allow_html=True)
