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
st.set_page_config(page_title="台股快速潛力股挖掘與 K 線診斷系統", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .main { background-color: #F8F9FA; }
    div.block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .stSelectbox, .stSlider, .stNumberInput { margin-bottom: 4px; }
</style>
""", unsafe_allow_html=True)

if 'screener_results' not in st.session_state:
    st.session_state.screener_results = pd.DataFrame()

# --- 2. 資料獲取函式 (FinMind 180天數據 + yfinance 備份) ---
def get_finmind_data(stock_id):
    today = pd.Timestamp.today().strftime('%Y-%m-%d')
    start_date = (pd.Timestamp.today() - pd.Timedelta(days=250)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    parameters = {
        "dataset": "TaiwanStockPrice",
        "data_id": str(stock_id),
        "start_date": start_date,
        "end_date": today,
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
    
    ticker = f"{stock_id}.TW" if stock_id in twstock.codes and twstock.codes[stock_id].market == "上市" else f"{stock_id}.TWO"
    try:
        df = yf.download(ticker, period="250d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns]
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except:
        return None

def get_taiwan_stock_list():
    stock_data = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            stock_data.append({"code": code, "name": info.name, "ticker": f"{code}.TW" if info.market == "上市" else f"{code}.TWO"})
    return pd.DataFrame(stock_data)

# --- 3. 繪製美化白色 K 線圖的共用函式 (含紅線突破頸線、棕線突破切線、一年新高黑線) ---
def plot_beautified_chart(df_k, stock_title, ma_num):
    df_k = df_k.tail(180).copy()
    
    ma_col_name = f'MA{ma_num}'
    df_k[ma_col_name] = df_k['Close'].rolling(ma_num).mean()
    
    year_high = df_k['High'].max()
    recent_high = df_k['High'].iloc[-25:-1].max()

    # 計算近20日下降趨勢線（以高點連線延伸至當前）
    highs = df_k['High'].iloc[-30:]
    x_idx = np.arange(len(highs))
    # 簡單模擬近期下降趨勢線斜率與切點
    slope, intercept = np.polyfit(x_idx[-15:], highs.iloc[-15:], 1)
    trendline_y = slope * x_idx + intercept

    # 計算 MACD
    exp1 = df_k['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df_k['Close'].ewm(span=26, adjust=False).mean()
    df_k['DIF'] = exp1 - exp2
    df_k['MACD_Signal'] = df_k['DIF'].ewm(span=9, adjust=False).mean()
    df_k['MACD_Hist'] = df_k['DIF'] - df_k['MACD_Signal']

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

    # 紅色突破頸線 (水平實線)
    fig.add_shape(
        type="line", x0=df_k.index[-25], x1=df_k.index[-1],
        y0=recent_high, y1=recent_high,
        line=dict(color="#FF0000", width=2),
        row=1, col=1
    )
    fig.add_trace(plotly_go.Scatter(
        x=[df_k.index[-1]], y=[recent_high],
        mode="text", text=[f" 紅色突破頸線: {recent_high:.2f}"],
        textposition="bottom right", showlegend=False
    ), row=1, col=1)

    # 棕線：突破切線 (突破下降趨勢線)
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index[-30:], y=trendline_y,
        line=dict(color="#8B4513", width=2, dash="solid"),
        name="棕線 (突破切線/下降趨勢)"
    ), row=1, col=1)

    # 股價創一年新高處劃一條水平線 (黑線)
    fig.add_shape(
        type="line", x0=df_k.index[0], x1=df_k.index[-1],
        y0=year_high, y1=year_high,
        line=dict(color="#000000", width=1.5, dash="dash"),
        row=1, col=1
    )
    fig.add_trace(plotly_go.Scatter(
        x=[df_k.index[-1]], y=[year_high],
        mode="text", text=[f" 一年新高: {year_high:.2f}"],
        textposition="top left", showlegend=False
    ), row=1, col=1)

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

    fig.update_layout(
        title=dict(text=f"<b>{stock_title}</b> - 180天歷史日線圖", font=dict(size=14, color="#2D3748")),
        template="plotly_white",
        height=600,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

# --- 4. 高效多執行緒全市場掃描函式 ---
def fetch_and_analyze_single_stock(row, enable_macd_25ma, macd_ma_period,
                                    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
                                    enable_kd_cross, enable_tangle, enable_breakout, tangle_ma_period,
                                    logic_mode, min_vol, max_growth):
    sid = row['code']
    df = get_finmind_data(sid)
    if df is None or len(df) < 60:
        return None
        
    df = df.dropna(subset=['Close'])
    curr_price = df['Close'].iloc[-1]
    prev_close = df['Close'].iloc[-2] if len(df) > 1 else curr_price
    curr_vol = df['Volume'].iloc[-1]

    if curr_vol < (min_vol * 1000): return None
    change_pct = ((curr_price - prev_close) / prev_close) * 100
    if change_pct > max_growth: return None

    df['daily_change'] = df['Close'].pct_change() * 100
    recent_df = df.iloc[-60:]
    limit_up_count = (recent_df['daily_change'] >= 9.5).sum()

    # 策略 1: MACD 回踩 0 軸 + MA 支持
    cond_a = False
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

    # 策略 2: 前 N 天帶量漲停 + 量縮回踩自訂 MA
    cond_b = False
    if enable_limit_up_pullback:
        df['ma_b'] = df['Close'].rolling(limit_up_ma_period).mean()
        ma_b_curr = df['ma_b'].iloc[-1]
        df['vol_ma5'] = df['Volume'].rolling(5).mean()
        
        check_range = df.iloc[-limit_up_days:]
        had_limit_up_vol = ((check_range['daily_change'] >= 9.5) & (check_range['Volume'] > check_range['vol_ma5'] * 1.5)).any()
        is_vol_shrink = curr_vol < df['vol_ma5'].iloc[-1]
        is_touch_ma = (df['Low'].iloc[-1] <= ma_b_curr * 1.015) and (curr_price >= ma_b_curr * 0.985)
        
        cond_b = had_limit_up_vol and is_vol_shrink and is_touch_ma

    # 策略 3: 日 KD 金叉
    cond_c = False
    if enable_kd_cross:
        low_9 = df['Low'].rolling(9).min()
        high_9 = df['High'].rolling(9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        k = rsv.ewm(com=2).mean()
        d = k.ewm(com=2).mean()
        cond_c = (k.iloc[-2] <= d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1])

    # 策略 4: 均線糾結 + 量穩價縮
    cond_d = False
    if enable_tangle:
        ma5 = df['Close'].rolling(5).mean()
        ma10 = df['Close'].rolling(10).mean()
        ma20 = df['Close'].rolling(tangle_ma_period).mean()
        
        ma_max = pd.concat([ma5, ma10, ma20], axis=1).max(axis=1)
        ma_min = pd.concat([ma5, ma10, ma20], axis=1).min(axis=1)
        is_tangled = ((ma_max - ma_min) / ma_min < 0.025).iloc[-5:-1].any()
        
        vol_ma = df['Volume'].rolling(5).mean()
        is_vol_steady = df['Volume'].iloc[-5:-1].mean() < vol_ma.iloc[-1] * 1.3
        
        cond_d = is_tangled and is_vol_steady

    # 策略 5: 突破切線或下降趨勢線
    cond_e = False
    if enable_breakout:
        vol_ma = df['Volume'].rolling(5).mean()
        is_breakout = (curr_price > df['High'].iloc[-25:-1].max()) and (curr_vol > vol_ma.iloc[-1] * 1.2)
        cond_e = is_breakout

    active_checks = []
    if enable_macd_25ma: active_checks.append(cond_a)
    if enable_limit_up_pullback: active_checks.append(cond_b)
    if enable_kd_cross: active_checks.append(cond_c)
    if enable_tangle: active_checks.append(cond_d)
    if enable_breakout: active_checks.append(cond_e)

    if not active_checks:
        return None

    if logic_mode == "AND (所有勾選條件皆需成立)":
        if not all(active_checks): return None
    else:
        if not any(active_checks): return None

    return {
        "股票代號": sid,
        "股票名稱": row['name'],
        "當日漲幅(%)": round(change_pct, 2),
        "近N日漲停次數": int(limit_up_count),
        "成交量(張)": int(curr_vol / 1000),
        "收盤價": round(curr_price, 2)
    }

def run_quick_screener_parallel(
    enable_macd_25ma, macd_ma_period,
    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
    enable_kd_cross, enable_tangle, enable_breakout, tangle_ma_period,
    logic_mode, min_vol, max_growth
):
    df_stocks = get_taiwan_stock_list()
    found_targets = []
    total_count = len(df_stocks)
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    completed = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(
                fetch_and_analyze_single_stock, 
                row, enable_macd_25ma, macd_ma_period,
                enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
                enable_kd_cross, enable_tangle, enable_breakout, tangle_ma_period,
                logic_mode, min_vol, max_growth
            ): row for _, row in df_stocks.iterrows()
        }
        
        for future in as_completed(futures):
            completed += 1
            if completed % 15 == 0 or completed == total_count:
                progress_bar.progress(min(completed / total_count, 1.0))
                status_text.markdown(f"🔍 **篩選進度:** `{completed}/{total_count}` | 🔥 **符合:** `{len(found_targets)}` 檔")
            
            res = future.result()
            if res:
                found_targets.append(res)
                
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


# ==========================================
# 5. 左側控制台
# ==========================================
with st.sidebar:
    st.title("⚡ 快速潛力股挖掘 (獨立拆分)")
    st.divider()

    logic_mode = st.radio(
        "🔀 篩選組合邏輯", 
        ["OR (符合任一勾選條件即可)", "AND (所有勾選條件皆需成立)"],
        index=0
    )
    st.divider()

    enable_macd_25ma = st.checkbox("1. MACD 回踩 0 軸 + MA 支持", value=True)
    macd_ma_period = st.number_input("MACD 搭配均線數值", min_value=1, max_value=240, value=25)

    enable_limit_up_pullback = st.checkbox("2. 前 N 天帶量漲停 + 量縮回踩 MA", value=False)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        limit_up_days = st.number_input("前 N 天", min_value=1, max_value=60, value=20)
    with col_p2:
        limit_up_ma_period = st.number_input("回踩 MA", min_value=1, max_value=240, value=25)

    enable_kd_cross = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)

    enable_tangle = st.checkbox("4. 均線糾結 + 量穩價縮", value=True)
    tangle_ma_period = st.number_input("糾結基準長 MA 數值", min_value=1, max_value=240, value=20)

    enable_breakout = st.checkbox("5. 突破切線或下降趨勢線", value=False)

    st.divider()
    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=5.0, step=0.5)

    btn_quick_search = st.button("🚀 執行組合潛力股挖掘", use_container_width=True, type="primary")

    st.divider()
    st.subheader("🩺 個股即時 K 線圖診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 2330")
    diag_btn = st.button("🔎 產出即時 K 線圖", use_container_width=True)


# ==========================================
# 6. 右側主畫面區塊
# ==========================================
st.title("📈 台股智慧選股與即時 K 線診斷系統")
st.caption("支援策略 4 與 5 獨立拆分搜尋，紅線為突破頸線，棕線為突破切線。")
st.divider()

# 個股即時 K 線圖診斷邏輯
if diag_btn and diag_code:
    with st.spinner(f"正在從 FinMind 擷取 {diag_code} 180天歷史數據並繪製即時 K 線圖..."):
        df_diag = get_finmind_data(diag_code)
        if df_diag is not None and not df_diag.empty:
            stock_list_df = get_taiwan_stock_list()
            matched_row = stock_list_df[stock_list_df['code'] == str(diag_code)]
            s_name = matched_row['name'].values[0] if not matched_row.empty else "未知公司"
            
            st.success(f"📊 股票代號 {diag_code} ({s_name}) 即時 K 線圖診斷報告")
            fig_diag = plot_beautified_chart(df_diag, f"{diag_code} {s_name} 即時診斷", macd_ma_period)
            st.plotly_chart(fig_diag, use_container_width=True)
        else:
            st.error(f"❌ 查無 {diag_code} 的歷史數據，請確認代號是否正確。")

st.subheader("📋 搜尋股票結果清單")

if btn_quick_search:
    with st.spinner("⚡ 正在透過多執行緒高速掃描全市場..."):
        res_df = run_quick_screener_parallel(
            enable_macd_25ma, macd_ma_period,
            enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
            enable_kd_cross, enable_tangle, enable_breakout, tangle_ma_period,
            logic_mode, min_vol, max_growth
        )
        st.session_state.screener_results = res_df

res_table = st.session_state.screener_results
if not res_table.empty:
    st.success(f"🎉 掃描完成！共找到 `{len(res_table)}` 檔符合條件的優質標的：")
    
    display_cols = ["股票代號", "股票名稱", "當日漲幅(%)", "近N日漲停次數", "成交量(張)"]
    st.dataframe(res_table[display_cols], use_container_width=True)

    st.divider()
    st.subheader("📈 下拉選擇標的查看詳細美化 K 線圖")
    selected_stock = st.selectbox(
        "請選擇欲檢視的股票代號",
        options=res_table["股票代號"].tolist(),
        format_func=lambda x: f"{x} - {res_table[res_table['股票代號']==x]['股票名稱'].values[0]}"
    )

    if selected_stock:
        with st.spinner(f"正在從 FinMind 載入 {selected_stock} 的 180 天歷史日線數據與指標..."):
            df_k = get_finmind_data(selected_stock)
            if df_k is not None and not df_k.empty:
                stock_name = res_table[res_table['股票代號']==selected_stock]['股票名稱'].values[0]
                fig_res = plot_beautified_chart(df_k, f"{selected_stock} {stock_name}", macd_ma_period)
                st.plotly_chart(fig_res, use_container_width=True)
            else:
                st.warning("⚠️ 無法獲取該標的的歷史數據。")
else:
    st.info("👈 請於左側勾選想組合的策略、切換篩選邏輯，並點擊「執行組合潛力股挖掘」。")
