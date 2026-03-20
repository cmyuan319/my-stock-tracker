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
            time.sleep(1); st.rerun()
            return True
        except: pass
    
    # 登入畫面置中設計
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<h1 style='text-align: center; color: #003366; margin-top: 100px;'>🛋️ 個人資產紀錄網</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #666;'>請登入以管理您的個人股票與期貨資產</p>", unsafe_allow_html=True)
        try:
            res = supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": "https://reid-stock.streamlit.app/"}})
            st.link_button("🚀 用 Google 帳號安全登入", res.url, type="primary", use_container_width=True)
        except: 
            st.error("登入系統維護中")
    return False

if not login_ui(): st.stop()

# ==========================================
# 🗄️ 資料庫與自動補齊邏輯
# ==========================================
user_email = st.session_state["user_email"]
def load_data():
    res = supabase.table("user_data").select("*").eq("email", user_email).execute()
    defaults = {
        "fee_discount": 6.0, "pledge_amount": 0.0, "account_balance": 0.0, 
        "credit_loan": 0.0, "other_assets": 0.0, "buy_records": [], "realized_records": [], 
        "history": {}, "market_data": {}, "futures_capital": 0.0, "futures_records": [], 
        "futures_realized": [], "fee_fut_tx": 50.0, "fee_fut_mtx": 25.0, 
        "fee_fut_tmf": 10.0, "fee_fut_stf": 20.0
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

# --- 🚀 爬蟲與計算引擎 ---
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

# --- 彈出視窗對話框 ---
@st.dialog("⚙️ 交易手續費設定")
def show_settings_dialog():
    new_disc = st.number_input("股票手續費折數", value=float(db.get("fee_discount", 6.0)))
    st.markdown("#### ⚡ 期貨單邊手續費")
    c1, c2 = st.columns(2)
    ntx = c1.number_input("大台 (TX)", value=float(db.get("fee_fut_tx", 50.0)))
    nmtx = c2.number_input("小台 (MTX)", value=float(db.get("fee_fut_mtx", 25.0)))
    ntmf = c1.number_input("微台 (TMF)", value=float(db.get("fee_fut_tmf", 10.0)))
    nstf = c2.number_input("股期 (STF)", value=float(db.get("fee_fut_stf", 20.0)))
    if st.button("💾 儲存設定", type="primary", use_container_width=True):
        db["fee_discount"], db["fee_fut_tx"], db["fee_fut_mtx"], db["fee_fut_tmf"], db["fee_fut_stf"] = new_disc, ntx, nmtx, ntmf, nstf
        save_data(db); st.rerun()

@st.dialog("➕ 新增股票交易")
def add_stock_dialog():
    d, t = st.date_input("買進日期"), st.text_input("股票代號").upper()
    s, p = st.number_input("股數", min_value=1, step=1000), st.number_input("買進單價", min_value=0.01)
    if st.button("確認新增", type="primary", use_container_width=True):
        if t:
            with st.spinner("抓取最新股價中..."):
                pr, na = fetch_price(t); db["market_data"][t] = {"price": pr, "name": na}
                db["buy_records"].append({"id": int(time.time()), "date": str(d), "ticker": t, "shares": s, "price": p})
                save_data(db); st.rerun()

@st.dialog("⚡ 新增期貨部位")
def add_futures_dialog():
    d, t = st.date_input("建立日期"), st.text_input("商品代號", placeholder="提示：期貨前加 W").upper()
    fdir = 1 if "多" in st.selectbox("方向", ["做多 (+1)", "做空 (-1)"]) else -1
    m_str = st.selectbox("規格", ["大台 (200)", "小台 (50)", "微台 (10)", "股票期貨 (2000)", "小型股期 (100)", "自訂"])
    mult = int(re.search(r'\((\d+)\)', m_str).group(1)) if "(" in m_str else st.number_input("自訂乘數", min_value=1)
    l, p = st.number_input("口數", min_value=1), st.number_input("成交價格", min_value=0.01)
    if st.button("確認新增", type="primary", use_container_width=True):
        if t:
            with st.spinner("抓取最新報價中..."): 
                pr, na = fetch_price(t)
                db["futures_records"].append({"id": int(time.time()), "date": str(d), "ticker": t, "name": na if na != t else t, "direction": fdir, "multiplier": mult, "lots": l, "price": p})
                db["market_data"][t] = {"price": pr if pr > 0 else p, "name": na}
                save_data(db); st.rerun()

@st.dialog("🔍 股票分批明細")
def show_details_dialog(ticker, name):
    recs = sorted([r for r in db["buy_records"] if r["ticker"] == ticker], key=lambda x: x["date"], reverse=True)
    for r in recs:
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        c1.write(r["date"]); c2.write(f"{r['shares']:,} 股"); c3.write(f"${r['price']:.2f}")
        if c4.button("🗑️", key=f"del_{r['id']}", help="刪除此筆紀錄"):
            db["buy_records"] = [x for x in db["buy_records"] if x["id"] != r["id"]]
            save_data(db); st.rerun()

@st.dialog("🛒 賣出股票")
def show_sell_dialog(ticker, name):
    tot_s = sum(r["shares"] for r in db["buy_records"] if r["ticker"] == ticker)
    st.info(f"可賣出總股數：{tot_s:,} 股")
    sell_date, sell_shares = st.date_input("賣出日期"), st.number_input("賣出股數", min_value=1, max_value=tot_s, step=1000)
    sell_price = st.number_input("成交價格", value=float(db["market_data"].get(ticker, {"price": 0.0})["price"]))
    if st.button("確認賣出", type="primary", use_container_width=True):
        rem = sell_shares
        for r in sorted([x for x in db["buy_records"] if x["ticker"] == ticker], key=lambda x: x["date"]):
            if rem <= 0: break
            take = min(r["shares"], rem)
            db["realized_records"].append({"sell_date": str(sell_date), "ticker": ticker, "shares": take, "buy_price": r["price"], "sell_price": sell_price})
            r["shares"] -= take; rem -= take
        db["buy_records"] = [x for x in db["buy_records"] if x["shares"] > 0]
        save_data(db); st.rerun()

@st.dialog("✏️ 修改期貨成本")
def edit_fut_cost(f_id, f_name, cost):
    nc = st.number_input("新成本價格", value=float(cost))
    if st.button("確認修改", type="primary", use_container_width=True):
        for r in db["futures_records"]:
            if r["id"] == f_id: r["price"] = nc; break
        save_data(db); st.rerun()

@st.dialog("🛒 平倉期貨部位")
def close_fut(f_id, f_name, lots, fdir):
    sd, sl = st.date_input("平倉日期"), st.number_input("平倉口數", min_value=1, max_value=lots)
    sp = st.number_input("平倉價格", min_value=0.01)
    if st.button("確認平倉", type="primary", use_container_width=True):
        for r in db["futures_records"]:
            if r["id"] == f_id:
                db["futures_realized"].append({"sell_date": str(sd), "ticker": r["ticker"], "name": r["name"], "direction": r["direction"], "multiplier": r["multiplier"], "lots": sl, "buy_price": r["price"], "sell_price": sp})
                r["lots"] -= sl; break
        db["futures_records"] = [x for x in db["futures_records"] if x["lots"] > 0]
        save_data(db); st.rerun()


# ==========================================
# 🧮 核心計算邏輯 (預先計算所有數據)
# ==========================================
agg = {}
for r in db["buy_records"]:
    t = r["ticker"]
    if t not in agg: agg[t] = {"shares": 0, "cost_basis": 0}
    agg[t]["shares"] += r["shares"]; agg[t]["cost_basis"] += r["shares"] * r["price"]

tot_exp, tot_mv, stock_unrealized, display_data = 0, 0, 0, []
for t, d in agg.items():
    shares = d["shares"]
    info = db["market_data"].get(t, {"price": 0.0, "name": t})
    curr_p, name = info["price"], info["name"]
    mv = shares * curr_p; tot_mv += mv
    tot_exp += (mv * 2 if t.endswith("L") else mv)
    cost = calc_cost_profit(t, shares, d["cost_basis"]/shares)
    tax = mv * (0.001 if t.startswith("00") else 0.003)
    un_p = round(mv - (mv * 0.001425 * (db["fee_discount"]/10)) - tax - cost)
    stock_unrealized += un_p
    display_data.append({"ticker": t, "name": name, "shares": shares, "avg_cost": d["cost_basis"]/shares, "curr_p": curr_p, "mv": mv, "un_p": un_p, "ret": (un_p/cost)*100 if cost>0 else 0})

fut_unrealized, fut_exposure = 0, 0
for f in db["futures_records"]:
    cp = db["market_data"].get(f["ticker"], {"price": f["price"]})["price"]
    gross = (cp - f["price"]) * f["direction"] * f["multiplier"] * f["lots"]
    un = round(gross - calc_futures_cost(f["multiplier"], f["price"], f["lots"]) - calc_futures_cost(f["multiplier"], cp, f["lots"]))
    fut_unrealized += un; fut_exposure += (cp * f["multiplier"] * f["lots"])

fut_realized = sum(round((r["sell_price"] - r["buy_price"]) * r["direction"] * r["multiplier"] * r["lots"] - calc_futures_cost(r["multiplier"], r["buy_price"], r["lots"]) - calc_futures_cost(r["multiplier"], r["sell_price"], r["lots"])) for r in db["futures_realized"])
stock_realized = sum(calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"]) for r in db["realized_records"])

tot_profit = stock_unrealized + stock_realized + fut_unrealized + fut_realized
total_assets = float(db["account_balance"]) + tot_mv + float(db["other_assets"]) + (float(db["futures_capital"]) + fut_unrealized + fut_realized) - float(db["pledge_amount"]) - float(db["credit_loan"])
lev_str = f"{(tot_exp + fut_exposure) / total_assets:.2f}x" if total_assets > 0 else "0.00x"
m_ratio = (tot_mv / float(db["pledge_amount"]) * 100) if float(db["pledge_amount"]) > 0 else 0

# --- 🚀 每日 14:00 記錄歷史 ---
tz_tw = timezone(timedelta(hours=8))
now_tw = datetime.datetime.now(tz_tw)
if now_tw.hour >= 14:
    t_str = now_tw.strftime('%Y-%m-%d')
    if db["history"].get(t_str, {}).get("assets") != total_assets:
        db["history"][t_str] = {"profit": tot_profit, "assets": total_assets}
        save_data(db)


# ==========================================
# 🎨 側邊欄設計 (Sidebar Navigation)
# ==========================================
with st.sidebar:
    st.markdown("### 🛋️ 資產紀錄網")
    st.caption(f"👤 {user_email}")
    st.divider()
    
    # 導覽選單
    menu = st.radio("導覽選單", ["📊 總覽 Dashboard", "📈 股票投資 Stocks", "⚡ 期貨投資 Futures", "⚖️ 資金與設定 Settings"])
    
    st.divider()
    
    # 全域操作按鈕
    st.markdown("**快速操作**")
    if st.button("🔄 更新最新報價", use_container_width=True):
        with st.spinner("更新即時報價中..."):
            for t in {r["ticker"] for r in db["buy_records"]} | {f["ticker"] for f in db["futures_records"]}:
                p, n = fetch_price(t); db["market_data"][t] = {"price": p, "name": n}
            save_data(db); st.rerun()
            
    if st.button("🚪 登出系統", use_container_width=True):
        cookie_manager.delete("user_email")
        st.session_state.clear()
        st.rerun()


# ==========================================
# 🖥️ 主頁面內容 (根據側邊欄選擇切換)
# ==========================================

# ----------------- 📊 總覽 Dashboard -----------------
if menu == "📊 總覽 Dashboard":
    st.markdown(f"## 📊 資產總覽 <span style='font-size: 0.5em; color: gray;'>更新時間: {now_tw.strftime('%Y/%m/%d %H:%M')}</span>", unsafe_allow_html=True)
    
    # 頂部三大指標
    m1, m2, m3 = st.columns(3)
    m1.metric("💰 總淨資產", f"${total_assets:,.0f}")
    m2.metric("📈 歷史總獲利", f"${tot_profit:,.0f}")
    m3.metric("🛡️ 當前總曝險額", f"${tot_exp + fut_exposure:,.0f}")
    
    st.divider()
    
    # 圖表區域
    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        st.markdown("#### 📈 獲利走勢")
        if db["history"]:
            df_h = pd.DataFrame([{"日期": k, "總獲利": v["profit"]} for k, v in db["history"].items()]).set_index("日期")
            st.line_chart(df_h, use_container_width=True)
        else:
            st.info("尚無足夠的歷史資料可繪製圖表")

    with col_chart2:
        st.markdown("#### 📊 資產走勢")
        if db["history"]:
            df_a = pd.DataFrame([{"日期": k, "總資產": v["assets"]} for k, v in db["history"].items()]).set_index("日期")
            st.line_chart(df_a, use_container_width=True)
        else:
            st.info("尚無足夠的歷史資料可繪製圖表")
            
    st.markdown("<br><p style='text-align: center; color: #003366; font-style: italic;'>一步一腳印，一起發大財 💰</p>", unsafe_allow_html=True)


# ----------------- 📈 股票投資 Stocks -----------------
elif menu == "📈 股票投資 Stocks":
    c_title, c_btn = st.columns([4, 1])
    c_title.markdown("## 📈 股票投資管理")
    if c_btn.button("➕ 新增股票", type="primary", use_container_width=True): 
        add_stock_dialog()
        
    tab_stock1, tab_stock2 = st.tabs(["📉 股票現貨庫存", "💰 已實現損益"])
    
    with tab_stock1:
        if display_data:
            # 圓餅圖
            df_p = pd.DataFrame(display_data)
            fig = px.pie(df_p, values='mv', names='ticker', hole=0.6)
            fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=300)
            fig.add_annotation(text=f"總市值<br>TWD {tot_mv:,.0f}", showarrow=False, font_size=16)
            st.plotly_chart(fig, use_container_width=True)
            
            # 庫存卡片列表
            st.markdown("#### 📌 庫存明細")
            for s in display_data:
                # 判斷賺賠顏色
                profit_color = "red" if s['un_p'] > 0 else "green" if s['un_p'] < 0 else "gray"
                
                with st.expander(f"【{s['ticker']}】{s['name']} ｜ 現價: ${s['curr_p']:,.2f} ｜ 損益: ${s['un_p']:,}"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("總市值", f"${s['mv']:,.0f}")
                    c2.metric("未實現損益", f"${s['un_p']:,}")
                    c3.metric("報酬率", f"{s['ret']:.2f}%")
                    
                    c4, c5, c6 = st.columns(3)
                    c4.metric("總持有股數", f"{s['shares']:,} 股")
                    c5.metric("持有均價", f"${s['avg_cost']:.2f}")
                    c6.metric("最新現價", f"${s['curr_p']:.2f}")
                    
                    st.divider()
                    b1, b2, b3 = st.columns([1, 1, 2])
                    if b1.button("🔍 交易明細", key=f"d_{s['ticker']}", use_container_width=True): show_details_dialog(s['ticker'], s['name'])
                    if b2.button("🛒 賣出平倉", key=f"s_{s['ticker']}", use_container_width=True): show_sell_dialog(s['ticker'], s['name'])
        else: 
            st.info("目前無任何股票現貨庫存。")

    with tab_stock2:
        if db.get("realized_records"):
            # 按照賣出日期排序，最新的在上面
            realized_recs = sorted(db["realized_records"], key=lambda x: x["sell_date"], reverse=True)
            
            for r in realized_recs:
                p = calc_cost_profit(r["ticker"], r["shares"], r["buy_price"], r["sell_price"])
                name = db.get("market_data", {}).get(r["ticker"], {"name": r["ticker"]})["name"]
                
                with st.container(border=True):
                    sc1, sc2 = st.columns([3, 1])
                    sc1.markdown(f"**{r['sell_date']}** ｜ 【{r['ticker']}】 {name}")
                    sc2.markdown(f"<span style='color:{'red' if p>0 else 'green'}; font-weight:bold; font-size:1.2em;'>${p:,}</span>", unsafe_allow_html=True)
                    
                    c1, c2, c3 = st.columns(3)
                    c1.caption(f"賣出股數: {r['shares']:,}")
                    c2.caption(f"買進單價: ${r['buy_price']:.2f}")
                    c3.caption(f"賣出單價: ${r['sell_price']:.2f}")
        else:
            st.info("目前還沒有任何已實現的股票賣出紀錄。")


# ----------------- ⚡ 期貨投資 Futures -----------------
elif menu == "⚡ 期貨投資 Futures":
    c_title, c_btn = st.columns([4, 1])
    c_title.markdown("## ⚡ 期貨投資管理")
    if c_btn.button("➕ 新增期貨", type="primary", use_container_width=True): 
        add_futures_dialog()
        
    st.markdown(f"#### 💰 當前期貨總帳戶權益: **${float(db['futures_capital']) + fut_unrealized + fut_realized:,.0f}**")
    
    tab_fut1, tab_fut2 = st.tabs(["⚡ 未平倉部位", "💰 已實現損益"])
    
    with tab_fut1:
        if db["futures_records"]:
            for f in db["futures_records"]:
                cp = db["market_data"].get(f["ticker"], {"price": f["price"]})["price"]
                un = round((cp - f["price"]) * f["direction"] * f["multiplier"] * f["lots"] - calc_futures_cost(f["multiplier"], f["price"], f["lots"]) - calc_futures_cost(f["multiplier"], cp, f["lots"]))
                dir_str = "🔴 做多" if f['direction']==1 else "🟢 做空"
                
                with st.expander(f"{dir_str} ｜【{f['ticker']}】{f['name']} ({f['lots']}口) ｜ 現價: {cp} ｜ 損益: ${un:,.0f}"):
                    fc1, fc2, fc3 = st.columns(3)
                    fc1.metric("建倉成本", f"{f['price']}")
                    fc2.metric("最新報價", f"{cp}")
                    fc3.metric("稅後淨損益", f"${un:,.0f}")
                    
                    st.divider()
                    _, e1, c1 = st.columns([2, 1, 1])
                    if e1.button("✏️ 修改成本", key=f"e_{f['id']}", use_container_width=True): edit_fut_cost(f['id'], f['name'], f['price'])
                    if c1.button("🛒 平倉", key=f"c_{f['id']}", type="primary", use_container_width=True): close_fut(f['id'], f['name'], f['lots'], f['direction'])
        else:
            st.info("目前無任何未平倉期貨部位。")
            
    with tab_fut2:
        if db.get("futures_realized"):
            fut_realized_recs = sorted(db["futures_realized"], key=lambda x: x["sell_date"], reverse=True)
            for r in fut_realized_recs:
                p = round((r["sell_price"] - r["buy_price"]) * r["direction"] * r["multiplier"] * r["lots"] - calc_futures_cost(r["multiplier"], r["buy_price"], r["lots"]) - calc_futures_cost(r["multiplier"], r["sell_price"], r["lots"]))
                dir_str = "多" if r['direction']==1 else "空"
                
                with st.container(border=True):
                    sc1, sc2 = st.columns([3, 1])
                    sc1.markdown(f"**{r['sell_date']}** ｜ 【{r['ticker']}】 {r['name']} ({dir_str} {r['lots']}口)")
                    sc2.markdown(f"<span style='color:{'red' if p>0 else 'green'}; font-weight:bold; font-size:1.2em;'>${p:,}</span>", unsafe_allow_html=True)
                    
                    c1, c2 = st.columns(2)
                    c1.caption(f"建倉價: {r['buy_price']}")
                    c2.caption(f"平倉價: {r['sell_price']}")
        else:
            st.info("目前無任何期貨平倉紀錄。")


# ----------------- ⚖️ 資金與設定 Settings -----------------
elif menu == "⚖️ 資金與設定 Settings":
    c_title, c_btn = st.columns([4, 1])
    c_title.markdown("## ⚖️ 資金控管與系統設定")
    if c_btn.button("⚙️ 修改手續費", use_container_width=True): 
        show_settings_dialog()
        
    st.markdown("### 🛡️ 核心風險指標")
    with st.container(border=True):
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("槓桿倍數", lev_str, help="總曝險額 / 總淨資產")
        rc2.metric("質押維持率", f"{m_ratio:.1f}%", help="(總市值 / 質押金額) * 100")
        rc3.metric("總曝險額", f"${tot_exp + fut_exposure:,.0f}", help="股票現貨(含槓桿ETF) + 期貨契約總值")
    
    st.markdown("### 💵 帳戶資金設定")
    with st.container(border=True):
        ec1, ec2 = st.columns(2)
        nb = ec1.number_input("🏦 銀行活存餘額", value=float(db["account_balance"]), step=10000.0)
        nfc = ec2.number_input("⚡ 期貨保證金本金", value=float(db["futures_capital"]), step=10000.0)
        
        ec3, ec4 = st.columns(2)
        np = ec3.number_input("📉 股票質押借款金額", value=float(db["pledge_amount"]), step=10000.0)
        ncl = ec4.number_input("💳 個人信貸金額", value=float(db["credit_loan"]), step=10000.0)
        
        no = st.number_input("🏡 其他資產 (如房地產/定存)", value=float(db["other_assets"]), step=10000.0)
        
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 儲存資金設定並更新數據", type="primary", use_container_width=True):
            db["account_balance"], db["futures_capital"], db["pledge_amount"], db["credit_loan"], db["other_assets"] = nb, nfc, np, ncl, no
            save_data(db)
            st.success("✅ 資金設定更新完成！")
            time.sleep(1)
            st.rerun()
