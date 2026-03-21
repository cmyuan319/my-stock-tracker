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
# 💡 網頁名稱固定，並且預設折疊側邊欄（如果有打開的話）
st.set_page_config(page_title="財富自由之路", layout="wide", page_icon="📈", initial_sidebar_state="collapsed")

# ==========================================
# 📱 🚀 手機版視覺優化 CSS + 👻 隱藏官方 UI 終極版
# ==========================================
st.markdown("""
    <style>
    html, body, [class*="css"] { font-family: 'PingFang TC', 'Microsoft JhengHei', sans-serif; }
    
    @media (max-width: 768px) {
        /* 🔥 強制所有分欄區塊「轉成橫向」，絕對不准變直的疊起來！ */
        div[data-testid="stColumns"],
        div[data-testid="stHorizontalBlock"],
        div[data-testid="stColumnLayout"],
        div[class*="stColumns"],
        div[class*="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: stretch !important;
            gap: 6px !important;
        }
        
        /* 強制平分寬度，絕對不准擠成兩排 */
        div[data-testid="stColumn"],
        div[data-testid="column"],
        div[class*="stColumn"] {
            flex: 1 1 0% !important;
            width: 100% !important;
            min-width: 0 !important;
            padding: 0 !important;
            display: block !important;
        }
        
        /* 按鈕化身為券商 APP 的精緻觸控方塊 */
        .stButton button { 
            height: 38px !important; 
            min-height: 38px !important;
            max-height: 38px !important;
            padding: 0px !important; 
            font-size: 18px !important; 
            width: 100% !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            border-radius: 6px !important;
            margin: 0 !important;
        }

        /* 確保千萬等級的數字能自動換行完整顯示 */
        [data-testid="stMetricValue"] {
            font-size: 1.4rem !important; 
            white-space: normal !important; 
            word-wrap: break-word !important;
            line-height: 1.1 !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 11px !important;
        }
        
        /* 縮減手機版的無效留白 */
        .block-container { 
            padding-top: 1rem !important; 
            padding-bottom: 0rem !important; 
        }
        .stTabs [data-baseweb="tab"] { 
            padding-left: 5px !important; 
            padding-right: 5px !important; 
            font-size: 14px !important; 
        }
    }

    /* ========================================== */
    /* 👻 徹底消滅 Streamlit 官方預設 UI (全域套用) */
    /* ========================================== */
    
    /* 1. 隱藏整個頂部 Header (包含 Deploy、GitHub、Share、漢堡選單) */
    [data-testid="stHeader"] {
        display: none !important;
    }
    
    /* 2. 隱藏右側工具列 (保險起見再加一層) */
    [data-testid="stToolbar"] {
        display: none !important;
    }
    
    /* 3. 隱藏頂部彩色裝飾條 */
    [data-testid="stDecoration"] {
        display: none !important;
    }
    
    /* 4. 隱藏底部 Footer (Made with Streamlit) */
    [data-testid="stFooter"], footer {
        display: none !important;
    }
    
    /* 5. 隱藏右下角的 Manage App 浮動按鈕 */
    .viewerBadge_container__1QSob,
    .viewerBadge_link__1S137,
    .viewerBadge_text__1JaDK,
    [class^="viewerBadge"] {
        display: none !important;
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
    
    st.markdown("<h1 style='text-align: center; color: #003366; margin-top: 50px;'>🛋️ 財富自由之路</h1>", unsafe_allow_html=True)
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
        "futures_capital": 0.0
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
    for url, tag in [(f"https://www.wantgoo.com/stock/{t_l}", 'span')]:
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
        
    if price == 0.0:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{ticker}"
            resp_y = requests.get(url_y, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            soup_y = BeautifulSoup(resp_y.text, 'html.parser')
            if name == ticker:
                title_tag = soup_y.find('title')
                if title_tag:
                    extracted_name = title_tag.text.split('(')[0].strip()
                    if "Yahoo" not in extracted_name: name = extracted_name
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

# --- 彈出視窗 ---
@st.dialog("⚙️ 設定中心")
def show_settings():
    new_disc = st.number_input("股票手續費折數", value=float(db["fee_discount"]))
    if st.button("💾 儲存並關閉", type="primary", use_container_width=True):
        db["fee_discount"] = new_disc
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

futures_equity = float(db.get("futures_capital", 0.0))

total_assets = float(db["account_balance"]) + tot_mv + float(db["other_assets"]) + futures_equity - float(db["pledge_amount"]) - float(db["credit_loan"])
total_profit = stock_unrealized + stock_realized
lev_str = f"{tot_exp / total_assets:.2f}x" if total_assets > 0 else "0.00x"
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
m1, m2 = st.columns(2)
m1.metric("總淨資產", f"${total_assets:,.0f}")
m2.metric("總獲利", f"${total_profit:,.0f}")

st.divider()

# 💡 純圖示按鈕
c_a, c_set, c_up, c_out = st.columns(4)
with c_a:
    if st.button("➕", help="新增股票", use_container_width=True): add_stock()
with c_set:
    if st.button("⚙️", help="設定", use_container_width=True): show_settings()
with c_up:
    if st.button("🔄", help="更新報價", use_container_width=True):
        with st.spinner("更新中..."):
            for t in {r["ticker"] for r in db["buy_records"]}:
                p, n = fetch_price(t); db["market_data"][t] = {"price": p, "name": n}
        save_data(db); st.rerun()
with c_out:
    if st.button("🚪", help="登出", use_container_width=True): cookie_manager.delete("user_email"); st.session_state.clear(); st.rerun()

t1, t2, t3, t4, t5 = st.tabs(["📉庫存", "💰已實現", "📈獲利", "📊資產", "⚖️資金"])

with t1:
    if display_stocks:
        df_p = pd.DataFrame(display_stocks)
        
        # 💡 左邊迷你圓餅圖，右邊前五大持股
        c_pie, c_list = st.columns(2)
        
        with c_pie:
            fig = px.pie(df_p, values='mv', names='ticker', hole=0.6)
            fig.update_layout(height=200, showlegend=False, margin=dict(t=0, b=0, l=0, r=0))
            fig.add_annotation(text=f"TWD<br>{tot_mv:,.0f}", showarrow=False, font_size=13)
            st.plotly_chart(fig, use_container_width=True)
            
        with c_list:
            st.markdown("<div style='padding-left: 5px; padding-top: 15px;'>", unsafe_allow_html=True)
            st.markdown("<div style='font-size: 14px; font-weight: bold; color: #555; margin-bottom: 8px;'>🏆 前五大持股</div>", unsafe_allow_html=True)
            top5 = df_p.nlargest(5, 'mv')
            for _, row in top5.iterrows():
                pct = (row['mv'] / tot_mv) * 100
                name_short = str(row['name'])[:4] 
                st.markdown(f"<div style='font-size: 12px; margin-bottom: 5px; border-bottom: 1px solid #eee; padding-bottom: 3px;'>"
                            f"<b>{row['ticker']}</b> <span style='color: #888;'>{name_short}</span>"
                            f"<span style='float: right; color: #d9534f; font-weight: bold;'>{pct:.1f}%</span></div>", 
                            unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        
        for s in display_stocks:
            with st.expander(f"【{s['ticker']}】{s['name']} ｜ ${s['curr_p']:,.1f}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("即時庫存", f"{s['shares']:,}")
                c2.metric("現值", f"${s['mv']:,.0f}")
                c3.metric("成本均價", f"${s['avg_cost']:.2f}")
                
                c4, c5, c6 = st.columns(3)
                c4.metric("現價", f"${s['curr_p']:.2f}")
                c5.metric("損益", f"${s['un_p']:,}")
                c6.metric("獲利率", f"{s['ret']:.2f}%")
                
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("🔍明細", key=f"d_{s['ticker']}", use_container_width=True): show_details(s['ticker'], s['name'])
                with b2:
                    if st.button("🛒賣出", key=f"s_{s['ticker']}", use_container_width=True): sell_stock(s['ticker'], s['name'])
    else: st.info("無現貨庫存")

with t2:
    if db.get("realized_records"):
        for r in sorted(db["realized_records"], key=lambda x: x["sell_date"], reverse=True):
            ticker = r["ticker"]
            shares = r["shares"]
            bp = r["buy_price"]
            sp = r["sell_price"]
            disc = db.get("fee_discount", 6.0) / 10.0
            buy_cost = shares * bp
            buy_fee = buy_cost * 0.001425 * disc
            sell_rev = shares * sp
            sell_fee = sell_rev * 0.001425 * disc
            tax_rate = 0.001 if ticker.startswith("00") else 0.003
            sell_tax = sell_rev * tax_rate
            total_cost = buy_cost + buy_fee
            net_profit = round(sell_rev - sell_fee - sell_tax - total_cost)
            roi = (net_profit / total_cost) * 100 if total_cost > 0 else 0
            
            with st.expander(f"{r['sell_date']} ｜ {ticker} ｜ 淨損益: ${net_profit:,}"):
                st.markdown(f"**交易:** {shares:,}股 ｜ **均進:** ${bp:.2f} ｜ **均出:** ${sp:.2f}")
                c1, c2, c3 = st.columns(3)
                c1.metric("總成本", f"${round(total_cost):,}")
                c2.metric("手續費", f"${round(buy_fee + sell_fee):,}")
                c3.metric("交易稅", f"${round(sell_tax):,}")
                c4, c5, c6 = st.columns(3)
                c4.metric("賣出總額", f"${round(sell_rev):,}")
                c5.metric("淨損益", f"${net_profit:,}")
                c6.metric("報酬率", f"{roi:.2f}%")
    else: st.info("無賣出紀錄")

with t3:
    if db["history"]:
        st.line_chart(pd.DataFrame([{"日期": k, "獲利": v["profit"]} for k, v in db["history"].items()]).set_index("日期"))

with t4:
    if db["history"]:
        st.line_chart(pd.DataFrame([{"日期": k, "資產": v["assets"]} for k, v in db["history"].items()]).set_index("日期"))

with t5:
    st.markdown("#### 🛡️ 風險指標")
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("槓桿倍數", lev_str)
    rc2.metric("維持率", f"{m_ratio:.0f}%")
    rc3.metric("總曝險", f"${tot_exp:,.0f}")
    st.divider()
    
    st.markdown("#### ⚖️ 資金手動調整")
    c1, c2 = st.columns(2)
    nb = c1.number_input("銀行餘額", value=float(db["account_balance"]))
    nfc = c2.number_input("期貨權益數", value=float(db.get("futures_capital", 0.0))) 
    np = c1.number_input("質押金額", value=float(db["pledge_amount"]))
    ncl = c2.number_input("信貸金額", value=float(db["credit_loan"]))
    no = st.number_input("其他資產", value=float(db["other_assets"]))
    
    if st.button("💾 確認更新資料庫", type="primary", use_container_width=True):
        db["account_balance"], db["futures_capital"], db["pledge_amount"], db["credit_loan"], db["other_assets"] = nb, nfc, np, ncl, no
        save_data(db); st.success("已更新！"); time.sleep(1); st.rerun()

st.markdown("<h1 style='text-align: center; color: #003366; font-size: 28px;'>財富自由之路 💰</h1>", unsafe_allow_html=True)
