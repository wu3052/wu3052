import time
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import twstock
import requests
import plotly.graph_objects as plotly_go
from plotly.subplots import make_subplots
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 頁面配置與簡潔美化 CSS ---
st.set_page_config(page_title="台股潛力股挖掘與 K 線診斷系統", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .main { background-color: #F8F9FA; }
    div.block-container { padding-top: 2rem; padding-bottom: 2rem; }
</style>
""", unsafe_allow_html=True)

if 'screener_results' not in st.session_state:
    st.session_state.screener_results = pd.DataFrame()

# --- 2. 資料獲取函式 (FinMind 180天數據 + yfinance 備份) ---
def get_finmind_data(stock_id, token=""):
    today = pd.Timestamp.today().strftime('%Y-%m-%d')
    start_date = (pd.Timestamp.today() - pd.Timedelta(days=260)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    parameters = {
        "dataset": "TaiwanStockPrice",
        "data_id": str(stock_id),
        "start_date": start_date,
        "end_date": today,
        "token": token
    }
    try:
        response = requests.get(url, params=parameters, timeout=5)
        data = response.json()
        if data.get("status") == 200 and data.get("data"):
            df = pd.DataFrame(data["data"])
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            df = df.rename(columns={
                'open': 'Open', 'max': 'High', 'min': 'Low', 
                'close': 'Close', 'Trading_Volume': 'Volume'
            })
            return df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    except:
        pass
    
    # 備份：使用 yfinance 抓取 180 天以上數據
    ticker = f"{stock_id}.TW" if stock_id in twstock.codes and twstock.codes[stock_id].market == "上市" else f"{stock_id}.TWO"
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns]
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except:
        return None

def get_taiwan_stock_list(market_scope="上市上櫃"):
    stock_data = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            if market_scope == "上市" and info.market != "上市": continue
            if market_scope == "上櫃" and info.market != "上櫃": continue
            stock_data.append({"code": code, "name": info.name, "ticker": f"{code}.TW" if info.market == "上市" else f"{code}.TWO"})
    return pd.DataFrame(stock_data)

# --- 3. 繪製美化白色 K 線圖的共用函式 (含 MACD、成交量、橘色實線形態與一年新高黑線) ---
def plot_beautified_chart(df_k, stock_title, ma_num):
    # 取最近 180 天顯示
    df_k = df_k.tail(180)
    
    ma_col_name = f'MA{ma_num}'
    df_k[ma_col_name] = df_k['Close'].rolling(ma_num).mean()
    
    # 計算一年新高 (取 240 天或現有資料中的最高價)
    year_high = df_k['High'].max()

    # 計算 MACD
    exp1 = df_k['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df_k['Close'].ewm(span=26, adjust=False).mean()
    df_k['DIF'] = exp1 - exp2
    df_k['MACD_Signal'] = df_k['DIF'].ewm(span=9, adjust=False).mean()
    df_k['MACD_Hist'] = df_k['DIF'] - df_k['MACD_Signal']

    # 建立 3 子圖 (K線 + 成交量 + MACD)
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.6, 0.2, 0.2]
    )

    # 1. 頂部 K 線圖與自訂紫色均線
    fig.add_trace(plotly_go.Candlestick(
        x=df_k.index, open=df_k['Open'], high=df_k['High'],
        low=df_k['Low'], close=df_k['Close'], name="K線",
        increasing_line_color='#EF5350', decreasing_line_color='#26A69A'
    ), row=1, col=1)

    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k[ma_col_name], 
        line=dict(color='#8A2BE2', width=2), 
        name=f"{ma_col_name} (均線)"
    ), row=1, col=1)

    # 形態趨勢線（橘色實線）
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index[-20:], y=df_k['Close'].iloc[-20:] * 0.98,
        line=dict(color='#FF9F43', width=2), 
        name="形態趨勢線"
    ), row=1, col=1)

    # 股價創一年新高水平線 (黑線)
    fig.add_hline(
        y=year_high, line_dash="solid",
        line=dict(color="#000000", width=1.5),
        annotation_text=f"一年新高: {year_high:.2f}",
        annotation_position="top left",
        row=1, col=1
    )

    # 2. 中間成交量
    colors = ['#EF5350' if row['Close'] >= row['Open'] else '#26A69A' for _, row in df_k.iterrows()]
    fig.add_trace(plotly_go.Bar(
        x=df_k.index, y=df_k['Volume'] / 1000, 
        marker_color=colors, name="成交量(張)"
    ), row=2, col=1)

    # 3. 底部 MACD
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['DIF'], line=dict(color='#2196F3', width=1.5), name="DIF"
    ), row=3, col=1)
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['MACD_Signal'], line=dict(color='#FF9800', width=1.5), name="MACD"
    ), row=3, col=1)
    
    macd_colors = ['#EF5350' if val >= 0 else '#26A69A' for val in df_k['MACD_Hist']]
    fig.add_trace(plotly_go.Bar(
        x=df_k.index, y=df_k['MACD_Hist'], marker_color=macd_colors, name="MACD Histogram"
    ), row=3, col=1)

    # 白色簡潔風格背景設定
    fig.update_layout(
        title=dict(text=f"<b>{stock_title}</b> - 180天歷史日線圖", font=dict(size=14, color="#2D3748")),
        template="plotly_white",
        height=620,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

# --- 4. 高效多執行緒全市場掃描函式 ---
def fetch_and_analyze_single_stock(row, search_period, limit_up_filter, 
                                    enable_macd_25ma, macd_ma_period,
                                    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
                                    enable_kd_cross, min_vol, max_growth, fm_token):
    sid = row['code']
    df = get_finmind_data(sid, fm_token)
    if df is None or len(df) < search_period:
        return None
        
    df = df.dropna(subset=['Close'])
    curr_price = df['Close'].iloc[-1]
    prev_close = df['Close'].iloc[-2] if len(df) > 1 else curr_price
    curr_vol = df['Volume'].iloc[-1]

    if curr_vol < (min_vol * 1000): return None
    change_pct = ((curr_price - prev_close) / prev_close) * 100
    if change_pct > max_growth: return None

    df['daily_change'] = df['Close'].pct_change() * 100
    recent_df = df.iloc[-search_period:]
    limit_up_count = (recent_df['daily_change'] >= 9.5).sum()

    if limit_up_filter != "不限":
        target_cnt = 5 if "5次以上" in limit_up_filter else int(limit_up_filter.replace("次", ""))
        if "5次以上" in limit_up_filter and limit_up_count < 5: return None
        elif "5次以上" not in limit_up_filter and limit_up_count != target_cnt: return None

    # 策略 A
    cond_a = True
    if enable_macd_25ma:
        df['ma_a'] = df['Close'].rolling(macd_ma_period).mean()
        ma_a_curr = df['ma_a'].iloc[-1]
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        dif = exp1 - exp2
        signal = dif.ewm(span=9, adjust=False).mean()
        
        cond_ma = (df['Low'].iloc[-1] <= ma_a_curr * 1.015) and (curr_price >= ma_a_curr * 0.985)
        cond_macd = (abs(dif.iloc[-1]) < (curr_price * 0.02)) and (dif.iloc[-1] > signal.iloc[-1])
        cond_a = cond_ma and cond_macd

    # 策略 B
    cond_b = True
    if enable_limit_up_pullback:
        df['ma_b'] = df['Close'].rolling(limit_up_ma_period).mean()
        ma_b_curr = df['ma_b'].iloc[-1]
        df['vol_ma5'] = df['Volume'].rolling(5).mean()
        
        check_range = df.iloc[-limit_up_days:]
        had_limit_up_vol = ((check_range['daily_change'] >= 9.5) & (check_range['Volume'] > check_range['vol_ma5'] * 1.5)).any()
        is_vol_shrink = curr_vol < df['vol_ma5'].iloc[-1]
        is_touch_ma = (df['Low'].iloc[-1] <= ma_b_curr * 1.015) and (curr_price >= ma_b_curr * 0.985)
        
        cond_b = had_limit_up_vol and is_vol_shrink and is_touch_ma

    # 策略 C
    cond_c = True
    if enable_kd_cross:
        low_9 = df['Low'].rolling(9).min()
        high_9 = df['High'].rolling(9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        k = rsv.ewm(com=2).mean()
        d = k.ewm(com=2).mean()
        cond_c = (k.iloc[-2] <= d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1])

    if not (cond_a and cond_b and cond_c): return None

    return {
        "股票代號": sid,
        "股票名稱": row['name'],
        "當日漲幅(%)": round(change_pct, 2),
        f"近{search_period}日漲停次數": int(limit_up_count),
        "成交量(張)": int(curr_vol / 1000),
        "收盤價": round(curr_price, 2)
    }

def run_quick_screener_parallel(
    market_scope, search_period, limit_up_filter, 
    enable_macd_25ma, macd_ma_period,
    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
    enable_kd_cross, min_vol, max_growth, fm_token
):
    df_stocks = get_taiwan_stock_list(market_scope)
    found_targets = []
    total_count = len(df_stocks)
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    completed = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(
                fetch_and_analyze_single_stock, 
                row, search_period, limit_up_filter, 
                enable_macd_25ma, macd_ma_period,
                enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
                enable_kd_cross, min_vol, max_growth, fm_token
            ): row for _, row in df_stocks.iterrows()
        }
        
        for future in as_completed(futures):
            completed += 1
            if completed % 15 == 0 or completed == total_count:
                progress_bar.progress(min(completed / total_count, 1.0))
                status_text.markdown(f"🔍 **掃描進度:** `{completed}/{total_count}` | 🔥 **符合:** `{len(found_targets)}` 檔")
            
            res = future.result()
            if res:
                found_targets.append(res)
                
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


# ==========================================
# 5. 左側版面配置 (保留獨立搜索與即時 K 線圖診斷)
# ==========================================
with st.sidebar:
    st.title("🎯 潛力股挖掘與診斷控制台")
    st.divider()

    fm_token = st.text_input("FinMind Token (選填)", value="", type="password", help="輸入後數據載入速度更快且更穩定")
    
    search_period = st.select_slider("1. 搜尋週期 (天數)", options=[20, 60, 90, 120, 240], value=60)
    market_scope = st.selectbox("2. 搜索範圍", ["上市上櫃", "上市", "上櫃"])
    limit_up_filter = st.selectbox("3. 近期漲停次數", ["不限", "0次", "1次", "2次", "3次", "4次", "5次", "5次以上"])

    st.divider()
    st.subheader("⚡ 快速潛力股挖掘 (獨立搜索)")
    
    enable_macd_25ma = st.checkbox("1. MACD 回踩 0 軸 + MA 支持", value=True)
    macd_ma_period = st.number_input("MACD 搭配均線數值", min_value=1, max_value=240, value=20)

    enable_limit_up_pullback = st.checkbox("2. 前 N 天帶量漲停 + 量縮回踩 MA", value=False)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        limit_up_days = st.number_input("前 N 天", min_value=1, max_value=60, value=20)
    with col_p2:
        limit_up_ma_period = st.number_input("回踩 MA", min_value=1, max_value=240, value=20)

    enable_kd_cross = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)

    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=5.0, step=0.5)

    btn_quick_search = st.button("🚀 執行全市場快速搜索", use_container_width=True, type="primary")

    st.divider()
    st.subheader("🩺 個股即時 K 線圖診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 2330")
    diag_btn = st.button("🔎 產出即時 K 線圖", use_container_width=True)


# ==========================================
# 6. 右側主畫面：個股即時診斷 K 線圖呈現
# ==========================================
if diag_btn and diag_code:
    with st.spinner(f"正在從 FinMind 擷取 {diag_code} 180天歷史數據並繪製即時 K 線圖..."):
        df_diag = get_finmind_data(diag_code, fm_token)
        if df_diag is not None and not df_diag.empty:
            st.success(f"📊 股票代號 {diag_code} 即時 K 線圖診斷報告")
            fig_diag = plot_beautified_chart(df_diag, f"{diag_code} 即時診斷", macd_ma_period)
            st.plotly_chart(fig_diag, use_container_width=True)
        else:
            st.error(f"❌ 查無 {diag_code} 的歷史數據，請確認代號是否正確。")

# ==========================================
# 7. 搜尋結果與高質感 K 線圖展示 (白色背景簡潔風格)
# ==========================================
st.subheader("📋 搜尋股票結果清單與詳細 K 線圖")

if btn_quick_search:
    with st.spinner("⚡ 正在透過多執行緒高速掃描全市場..."):
        res_df = run_quick_screener_parallel(
            market_scope, search_period, limit_up_filter,
            enable_macd_25ma, macd_ma_period,
            enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
            enable_kd_cross, min_vol, max_growth, fm_token
        )
        st.session_state.screener_results = res_df

res_table = st.session_state.screener_results
if not res_table.empty:
    st.success(f"🎉 掃描完成！共找到 `{len(res_table)}` 檔符合條件的優質標的：")
    st.dataframe(res_table, use_container_width=True)

    st.divider()
    st.subheader("📈 下拉選擇標的查看詳細美化 K 線圖")
    selected_stock = st.selectbox(
        "請選擇欲檢視的股票代號",
        options=res_table["股票代號"].tolist(),
        format_func=lambda x: f"{x} - {res_table[res_table['股票代號']==x]['股票名稱'].values[0]}"
    )

    if selected_stock:
        with st.spinner(f"正在從 FinMind 載入 {selected_stock} 的 180 天歷史日線數據與指標..."):
            df_k = get_finmind_data(selected_stock, fm_token)
            if df_k is not None and not df_k.empty:
                stock_name = res_table[res_table['股票代號']==selected_stock]['股票名稱'].values[0]
                fig_res = plot_beautified_chart(df_k, f"{selected_stock} {stock_name}", macd_ma_period)
                st.plotly_chart(fig_res, use_container_width=True)
            else:
                st.warning("⚠️ 無法獲取該標的的歷史數據。")
else:
    st.info("👈 請於左側調整條件並點擊「執行全市場快速搜索」，即可快速產出符合條件的潛力股與美化 K 線圖。")
