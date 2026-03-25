import streamlit as st
import pandas as pd
import datetime
from sqlalchemy import text
import plotly.express as px

# ==========================================
# 1. 数据库配置与多用户表初始化
# ==========================================
conn = st.connection("supabase", type="sql")

def init_db():
    with conn.session as s:
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS users_accounts (
                username TEXT PRIMARY KEY,
                password TEXT
            );
        '''))
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS private_glucose_logs (
                username TEXT,
                record_date DATE,
                fasting NUMERIC,
                postprandial NUMERIC,
                bedtime NUMERIC,
                PRIMARY KEY (username, record_date)
            );
        '''))
        s.commit()

# ==========================================
# 2. 账号注册与登录核心逻辑
# ==========================================
def register_user(username, password):
    with conn.session as s:
        result = s.execute(text("SELECT username FROM users_accounts WHERE username=:u"), {"u": username}).fetchone()
        if result:
            return False
        s.execute(text("INSERT INTO users_accounts (username, password) VALUES (:u, :p)"), {"u": username, "p": password})
        s.commit()
        return True

def verify_login(username, password):
    with conn.session as s:
        result = s.execute(text("SELECT password FROM users_accounts WHERE username=:u"), {"u": username}).fetchone()
        if result and result[0] == password:
            return True
        return False

# ==========================================
# 3. 个人专属数据存取逻辑
# ==========================================
def save_to_db(username, date, fasting, postprandial, bedtime):
    with conn.session as s:
        s.execute(text('''
            INSERT INTO private_glucose_logs (username, record_date, fasting, postprandial, bedtime)
            VALUES (:u, :d, :f, :p, :b)
            ON CONFLICT (username, record_date) DO UPDATE SET
                fasting = EXCLUDED.fasting,
                postprandial = EXCLUDED.postprandial,
                bedtime = EXCLUDED.bedtime;
        '''), {"u": username, "d": date, "f": fasting, "p": postprandial, "b": bedtime})
        s.commit()

def load_from_db(username):
    query = "SELECT record_date, fasting, postprandial, bedtime FROM private_glucose_logs WHERE username = :u ORDER BY record_date ASC"
    df = conn.query(query, params={"u": username}, ttl=0)
    return df

init_db()

# ==========================================
# 4. 前端界面展示 (登录墙 + 主系统)
# ==========================================
st.set_page_config(page_title="血糖监测与分析系统", layout="centered", page_icon="🩸")

if "logged_in_user" not in st.session_state:
    st.session_state["logged_in_user"] = None

if st.session_state["logged_in_user"] is None:
    st.title("🔐 血糖监测系统 - 登录")
    
    tab1, tab2 = st.tabs(["🔑 登录", "📝 注册账号"])
    
    with tab1:
        st.subheader("账号登录")
        login_u = st.text_input("用户名", key="login_u")
        login_p = st.text_input("密码", type="password", key="login_p")
        if st.button("登录", use_container_width=True):
            if verify_login(login_u, login_p):
                st.session_state["logged_in_user"] = login_u
                st.success("登录成功！正在进入系统...")
                st.rerun()
            else:
                st.error("用户名或密码错误，请重试。")
                
    with tab2:
        st.subheader("注册新账号")
        reg_u = st.text_input("设置用户名", key="reg_u")
        reg_p = st.text_input("设置密码", type="password", key="reg_p")
        if st.button("立即注册", use_container_width=True):
            if reg_u == "" or reg_p == "":
                st.warning("用户名和密码不能为空！")
            elif register_user(reg_u, reg_p):
                st.success(f"账号 '{reg_u}' 注册成功！请切换到左侧登录。")
            else:
                st.error("该用户名已被占用，请换一个。")

else:
    current_user = st.session_state["logged_in_user"]
    
    st.sidebar.title("用户信息")
    st.sidebar.info(f"当前登录：**{current_user}**")
    if st.sidebar.button("退出登录"):
        st.session_state["logged_in_user"] = None
        st.rerun()

    st.title("🩸 个人专属血糖监测面板")
    st.header("1. 录入今日数据")

    selected_date = st.date_input("请选择日期", datetime.date.today())

    col1, col2, col3 = st.columns(3)
    with col1:
        fasting_val = st.number_input("空腹血糖 (mmol/L)", min_value=0.0, max_value=35.0, step=0.1, format="%.1f")
    with col2:
        postprandial_val = st.number_input("餐后2h血糖 (mmol/L)", min_value=0.0, max_value=35.0, step=0.1, format="%.1f")
    with col3:
        bedtime_val = st.number_input("睡前血糖 (mmol/L)", min_value=0.0, max_value=35.0, step=0.1, format="%.1f")

    if st.button("同步至云端 (加密保存)"):
        save_to_db(current_user, selected_date, fasting_val, postprandial_val, bedtime_val)
        st.success(f"[{current_user}] {selected_date} 的数据已安全保存！")

    st.divider()
    st.header("2. 个人数据分析曲线")

    df_records = load_from_db(current_user)

    if not df_records.empty:
        df_records['record_date'] = pd.to_datetime(df_records['record_date'])
        
        # 导出功能 (保留最原始的数据格式供下载)
        csv_data = df_records.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 一键导出全部历史数据 (Excel CSV)",
            data=csv_data,
            file_name=f"{current_user}_专属血糖数据.csv",
            mime="text/csv",
            use_container_width=True
        )
        st.divider()

        # ==========================================
        # 核心升级：Plotly 交互式图表 & 去0处理
        # ==========================================
        st.subheader("📊 血糖波动趋势图 (交互式)")
        
        # 1. 复制一份数据专门用来画图，把所有的 0.0 替换成 None (NaN)
        # 这样遇到未录入的数据，图表会断开连线，而不是直接掉到 0
        df_plot = df_records.copy()
        df_plot[['fasting', 'postprandial', 'bedtime']] = df_plot[['fasting', 'postprandial', 'bedtime']].replace(0.0, None)

        # 2. 转换数据格式以适配 Plotly
        df_long = df_plot.melt(id_vars=['record_date'], 
                              value_vars=['fasting', 'postprandial', 'bedtime'],
                              var_name='时间段', value_name='血糖值')
        name_map = {'fasting': '空腹', 'postprandial': '餐后2h', 'bedtime': '睡前'}
        df_long['时间段'] = df_long['时间段'].map(name_map)

        # 3. 绘制带有数据点的专业折线图
        fig = px.line(df_long, 
                     x='record_date', 
                     y='血糖值', 
                     color='时间段',
                     markers=True,
                     color_discrete_map={'空腹': '#1f77b4', '餐后2h': '#ff7f0e', '睡前': '#2ca02c'})

        # 4. 图表细节深度美化
        fig.update_layout(
            hovermode="x unified", # 鼠标悬停显示同一天的所有数据
            xaxis=dict(
                title="日期",
                rangeslider=dict(visible=True), # 底部增加滑动缩放条，防卡顿神器
                type="date"
            ),
            yaxis=dict(title="血糖 (mmol/L)"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=0, r=0, t=30, b=0)
        )
        
        # 5. 增加一条绿色背景带，代表空腹血糖的健康参考范围 (3.9 - 6.1 mmol/L)
        fig.add_hrect(y0=3.9, y1=6.1, line_width=0, fillcolor="green", opacity=0.1, annotation_text="空腹参考区间", annotation_position="top left")

        # 将图表渲染到网页上
        st.plotly_chart(fig, use_container_width=True)
        
        st.divider()
        st.subheader("📃 原始数据记录表")
        
        # 展示用表格（把列名换成中文更好看）
        df_display = df_records.copy()
        df_display.set_index('record_date', inplace=True)
        df_display.rename(columns={'fasting': '空腹血糖', 'postprandial': '餐后2h血糖', 'bedtime': '睡前血糖'}, inplace=True)
        st.dataframe(df_display, use_container_width=True)

    else:
        st.info("您的账号暂无记录，请录入数据后查看。")
