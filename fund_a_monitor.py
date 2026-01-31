# 屏蔽无关警告
import warnings
warnings.filterwarnings("ignore", message="missing ScriptRunContext!")
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

import requests
import pandas as pd
import time
import streamlit as st
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# -------------------------- 【仅需修改这里】配置参数 --------------------------
# 基金本金（元）
PRINCIPAL = 16000
# 持仓数据（占比为小数，0.1021 = 10.21%）
holdings = pd.DataFrame({
    "股票代码": ["688619", "688258", "300624", "603171", "300364", "300170", "688500", "301171", "603039", "688365"],
    "股票名称": ["合合信息", "卓易信息", "万兴科技", "税友股份", "中文在线", "汉得信息", "慧辰股份", "易点天下", "泛微网络", "光云科技"],
    "持仓占比": [0.1021, 0.0980, 0.0794, 0.0739, 0.0627, 0.0613, 0.0531, 0.0512, 0.0509, 0.0503]
})
# Excel分母总占比（68.29% → 0.6829）
TOTAL_HOLD_RATIO = 0.6829
# 自动刷新间隔（秒，建议30-60秒）
REFRESH_INTERVAL = 30
# 持有收益基数
BASE_HOLD_EARNINGS = -435.84
# -----------------------------------------------------------------------------

# 初始化会话数据（历史涨跌幅+个股K线缓存）
if "history_data" not in st.session_state:
    st.session_state.history_data = pd.DataFrame(columns=["时间", "基金涨跌幅(%)", "实时收益(元)"])
if "stock_kline_cache" not in st.session_state:
    st.session_state.stock_kline_cache = {}  # 缓存个股K线数据，减少请求

# 同花顺实时数据爬取（返回：最新价、涨跌幅小数、今开、最高、最低、昨收）
def get_stock_real_data(stock_code):
    url = f"http://qt.gtimg.cn/q=s_{stock_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.10jqka.com.cn/"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        resp.encoding = "gbk"
        data = resp.text.split("~")
        if len(data) < 40:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        latest_price = float(data[3])    # 最新价
        change_rate = float(data[32])/100# 涨跌幅（小数）
        open_price = float(data[5])     # 今开
        high_price = float(data[33])    # 最高
        low_price = float(data[34])     # 最低
        pre_close = float(data[4])      # 昨收
        return latest_price, change_rate, open_price, high_price, low_price, pre_close
    except Exception as e:
        st.warning(f"⚠️ 【{stock_code}】实时数据获取失败：{str(e)[:20]}")
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

# 同花顺个股当日K线数据爬取（返回：时间轴、价格轴，用于绘制K线）
def get_stock_day_kline(stock_code, stock_name):
    # 若缓存未过期，直接返回缓存数据（避免重复请求）
    if stock_code in st.session_state.stock_kline_cache:
        cache_time, kline_data = st.session_state.stock_kline_cache[stock_code]
        if time.time() - cache_time < REFRESH_INTERVAL - 5:
            return kline_data
    
    # 同花顺当日分时K线接口，返回分时数据
    url = f"https://data.10jqka.com.cn/chart/hs/time/hs_klines/{stock_code}/1min/今日/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://www.10jqka.com.cn/stockpage/hs_{stock_code}/{stock_name}/"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        kline_data = resp.json()
        if not kline_data or "data" not in kline_data:
            return [], []
        # 解析K线数据：时间+价格
        times = [item[0].split(" ")[1] for item in kline_data["data"]]  # 提取时分
        prices = [float(item[1]) for item in kline_data["data"]]       # 提取价格
        # 更新缓存
        st.session_state.stock_kline_cache[stock_code] = (time.time(), (times, prices))
        return times, prices
    except Exception as e:
        st.warning(f"⚠️ 【{stock_name}】K线数据获取失败：{str(e)[:20]}")
        return [], []

# 核心计算：匹配Excel公式，基金涨跌幅+实时收益
def calculate_fund_metrics():
    holdings_detail = holdings.copy()
    weighted_sum = 0.0
    # 遍历持仓，获取实时数据并计算
    for idx, row in holdings_detail.iterrows():
        code, name = row["股票代码"], row["股票名称"]
        # 获取实时全量数据
        latest, change, open_p, high_p, low_p, pre_p = get_stock_real_data(code)
        # 赋值到明细表格
        holdings_detail.loc[idx, "最新价(元)"] = round(latest, 2)
        holdings_detail.loc[idx, "今开(元)"] = round(open_p, 2)
        holdings_detail.loc[idx, "最高(元)"] = round(high_p, 2)
        holdings_detail.loc[idx, "最低(元)"] = round(low_p, 2)
        holdings_detail.loc[idx, "昨收(元)"] = round(pre_p, 2)
        holdings_detail.loc[idx, "个股涨跌幅(%)"] = round(change * 100, 2)
        holdings_detail.loc[idx, "加权涨跌幅(%)"] = round(change * row["持仓占比"] * 100, 4)
        weighted_sum += change * row["持仓占比"]
    # 基金整体指标计算（匹配Excel公式）
    fund_change = round((weighted_sum / TOTAL_HOLD_RATIO) * 100, 2)
    real_earnings = round(PRINCIPAL * (weighted_sum / TOTAL_HOLD_RATIO), 2)
    hold_earnings = round(real_earnings + BASE_HOLD_EARNINGS, 2)
    return holdings_detail, fund_change, real_earnings, hold_earnings

# 保存基金历史涨跌幅数据
def save_history(fund_change, real_earnings):
    current_time = datetime.now().strftime("%H:%M:%S")
    new_data = pd.DataFrame({
        "时间": [current_time],
        "基金涨跌幅(%)": [fund_change],
        "实时收益(元)": [real_earnings]
    })
    st.session_state.history_data = pd.concat([st.session_state.history_data, new_data], ignore_index=True).tail(50)

# 绘制个股当日K线/分时走势（Plotly绘制，贴合股票软件风格）
def plot_stock_kline(stock_code, stock_name):
    times, prices = get_stock_day_kline(stock_code, stock_name)
    if not times or not prices:
        st.info(f"📉 【{stock_name}】暂无K线数据（非交易时间/数据获取失败）")
        return
    # 绘制分时K线图
    fig = go.Figure()
    # 主走势线（红色，贴合股票风格）
    fig.add_trace(go.Scatter(
        x=times, y=prices, mode="lines", name=stock_name,
        line=dict(color="#e63946", width=2), hovertemplate="时间：%{x}<br>价格：%{y:.2f}元"
    ))
    # 添加均线（5分钟均线，平滑走势）
    if len(prices) >= 5:
        ma5 = np.convolve(prices, np.ones(5)/5, mode="valid")
        ma5_times = times[2:-2] if len(times) == len(ma5)+4 else times[:len(ma5)]
        fig.add_trace(go.Scatter(
            x=ma5_times, y=ma5, mode="lines", name="5分钟均线",
            line=dict(color="#1982c4", width=1, dash="dash")
        ))
    # 图表样式配置
    fig.update_layout(
        title=f"{stock_name}（{stock_code}）当日分时K线",
        title_font_size=14, height=300, showlegend=True,
        xaxis_title="交易时间", yaxis_title="股价(元)",
        xaxis=dict(tickangle=45, tickfont_size=10),
        yaxis=dict(tickfont_size=10),
        margin=dict(l=10, r=10, t=40, b=20)
    )
    # 添加价格轴参考线（昨收价）
    _, _, _, _, _, pre_close = get_stock_real_data(stock_code)
    if pre_close > 0:
        fig.add_hline(
            y=pre_close, line_dash="dash", line_color="gray", line_width=1,
            annotation_text=f"昨收：{pre_close:.2f}", annotation_position="top right"
        )
    st.plotly_chart(fig, use_container_width=True)

# 主页面：基金监控+实时股价+K线走势
def main():
    st.set_page_config(page_title="基金A实时监控（含K线）", layout="wide", page_icon="💰")
    st.title("💰 基金A 实时涨跌幅监控（含个股K线）")
    st.caption(f"📊 数据来源：同花顺实时行情 | ⏳ 自动刷新：{REFRESH_INTERVAL}秒 | 💰 本金：{PRINCIPAL}元 | 🧮 计算方式：匹配Excel公式")
    st.divider()

    # 核心计算：获取持仓明细+基金指标
    holdings_detail, fund_change, real_earnings, hold_earnings = calculate_fund_metrics()
    save_history(fund_change, real_earnings)

    # 第一行：基金核心指标（涨跌幅/今日收益/持有收益）
    col1, col2, col3 = st.columns(3, gap="medium")
    delta_color = "inverse" if fund_change < 0 else "normal" if fund_change > 0 else "normal"
    with col1:
        st.metric("📈 基金实时涨跌幅", f"{fund_change}%", delta=f"{fund_change}%", delta_color=delta_color)
    with col2:
        st.metric("📊 今日预估收益", f"{real_earnings}元", delta=f"{real_earnings}元", delta_color=delta_color)
    with col3:
        st.metric("💵 累计持有收益", f"{hold_earnings}元", delta=f"{real_earnings}元", delta_color=delta_color)

    st.divider()

    # 第二行：持仓明细（含实时股价/今开/最高/最低）
    st.subheader("📋 持仓明细（含同花顺实时股价）")
    # 【关键修复】：新建显示用的列，不修改原始计算用的持仓占比
    holdings_detail["持仓占比_显示"] = holdings_detail["持仓占比"] * 100
    show_cols = [
        "股票代码", "股票名称", "持仓占比_显示", "最新价(元)", "今开(元)", "最高(元)",
        "最低(元)", "昨收(元)", "个股涨跌幅(%)", "加权涨跌幅(%)"
    ]
    st.dataframe(
        holdings_detail[show_cols],
        use_container_width=True, hide_index=True,
        column_config={
            "持仓占比_显示": st.column_config.NumberColumn("持仓占比", format="%.2f%%"),
            "最新价(元)": st.column_config.NumberColumn(format="%.2f"),
            "今开(元)": st.column_config.NumberColumn(format="%.2f"),
            "最高(元)": st.column_config.NumberColumn(format="%.2f"),
            "最低(元)": st.column_config.NumberColumn(format="%.2f"),
            "昨收(元)": st.column_config.NumberColumn(format="%.2f"),
            "个股涨跌幅(%)": st.column_config.NumberColumn(format="%.2f"),
            "加权涨跌幅(%)": st.column_config.NumberColumn(format="%.4f")
        }
    )
    # 计算逻辑验证
    weighted_sum = round(holdings_detail["加权涨跌幅(%)"].sum(), 4)
    st.success(f"✅ 加权涨跌幅和：{weighted_sum}% | 总占比：{TOTAL_HOLD_RATIO*100}% | 基金涨跌幅：{round(weighted_sum/(TOTAL_HOLD_RATIO*100)*100,2)}%")

    st.divider()

    # 第三行：双列布局（基金历史涨跌幅曲线 + 个股K线选择）
    col_left, col_right = st.columns([0.5, 0.5], gap="medium")
    with col_left:
        st.subheader("📈 基金近50次刷新涨跌幅曲线")
        if len(st.session_state.history_data) >= 2:
            fig = px.line(
                st.session_state.history_data, x="时间", y="基金涨跌幅(%)",
                markers=True, color_discrete_sequence=["#e63946"],
                hover_data={"实时收益(元)": True, "基金涨跌幅(%)": "%.2f%%"}
            )
            fig.update_layout(height=350, showlegend=False, xaxis_tickangle=45)
            fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("📌 等待数据刷新，即将绘制基金涨跌幅曲线...")

    with col_right:
        st.subheader("📉 个股当日分时K线走势（自选）")
        # 下拉选择个股，绘制对应K线
        stock_choice = st.selectbox(
            "选择查看K线的股票",
            options=[f"{row['股票名称']}（{row['股票代码']}）" for _, row in holdings_detail.iterrows()],
            index=0
        )
        # 解析选择的股票代码和名称
        stock_name = stock_choice.split("（")[0]
        stock_code = stock_choice.split("（")[1].replace("）", "")
        # 绘制K线
        plot_stock_kline(stock_code, stock_name)

    # 自动刷新逻辑
    st.divider()
    next_refresh = datetime.fromtimestamp(time.time() + REFRESH_INTERVAL).strftime("%H:%M:%S")
    st.info(f"🔄 下次全量数据刷新时间：{next_refresh}（K线数据同步刷新）")
    time.sleep(REFRESH_INTERVAL)
    st.rerun()

if __name__ == "__main__":
    main()