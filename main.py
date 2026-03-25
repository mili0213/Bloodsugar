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
# 新增功能：智能诊断逻辑引擎 (已更新个人标准)
# ==========================================
def judge_blood_sugar(value, time_type):
    """根据个人定制标准判断血糖高低"""
    if pd.isna(value) or value == 0.0 or value is None:
        return "未录入 ⚪"
        
    if time_type == 'fasting': # 空腹标准 4.4 - 7.0
        if value < 4.4:
            return "偏低 🔵"
        elif value <= 7.0:
            return "正常 🟢"
        else:
            return "偏高 🔴"
            
    elif time_type == 'postprandial': # 餐后两小时标准 < 10
        if value < 4.4:
            return "偏低 🔵"
        elif value <= 10.0:
            return "正常 🟢"
        else:
            return "偏高 🔴"
            
    elif time_type == 'bedtime': # 睡前标准 < 11
        if value < 4.4:
            return "偏低 🔵"
        elif value <= 11.0:
            return "正常 🟢"
        else:
            return "偏高 🔴"
            
    return "未知"

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
        
        f_status = judge_blood_sugar(fasting_val if fasting_val > 0 else None, 'fasting')
        p_status = judge_blood_sugar(postprandial_val if postprandial_val > 0 else None, 'postprandial')
        b_status = judge_blood_sugar(bedtime_val if bedtime_val > 0 else None, 'bedtime')
        
        st.success(f"[{selected_date}] 数据已安全保存！")
        st.info(f"**今日诊断反馈：** \n\n空腹: {f_status} | 餐后2h: {p_status} | 睡前: {b_status}")

    st.divider()
    st.header("2. 个人数据分析曲线")

    df_records = load_from_db(current_user)

    if not df_records.empty:
        df_records['record_date'] = pd.to_datetime(df_records['record_date'])
        
        csv_data = df_records.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 一键导出全部历史数据 (Excel CSV)",
            data=csv_data,
            file_name=f"{current_user}_专属血糖数据.csv",
            mime="text/csv",
            use_container_width=True
        )
        st.divider()

        st.subheader("📊 血糖波动趋势图 (交互式)")
        
        df_plot = df_records.copy()
        df_plot[['fasting', 'postprandial', 'bedtime']] = df_plot[['fasting', 'postprandial', 'bedtime']].replace(0.0, None)

        df_long = df_plot.melt(id_vars=['record_date'], 
                              value_vars=['fasting', 'postprandial', 'bedtime'],
                              var_name='时间段', value_name='血糖值')
        name_map = {'fasting': '空腹', 'postprandial': '餐后2h', 'bedtime': '睡前'}
        df_long['时间段'] = df_long['时间段'].map(name_map)

        fig = px.line(df_long, 
                     x='record_date', 
                     y='血糖值', 
                     color='时间段',
                     markers=True,
                     color_discrete_map={'空腹': '#1f77b4', '餐后2h': '#ff7f0e', '睡前': '#2ca02c'})

        fig.update_layout(
            hovermode="x unified",
            xaxis=dict(
                title="日期",
                rangeslider=dict(visible=True),
                type="date"
            ),
            yaxis=dict(title="血糖 (mmol/L)"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=0, r=0, t=30, b=0)
        )
        
        # 调整了图表中的绿色健康区间带，匹配 4.4 - 7.0
        fig.add_hrect(y0=4.4, y1=7.0, line_width=0, fillcolor="green", opacity=0.1, annotation_text="空腹正常区间 (4.4-7.0)", annotation_position="top left")

        st.plotly_chart(fig, use_container_width=True)
        
        st.divider()
        st.subheader("📃 历史数据与状态诊断表")
        
        df_display = df_plot.copy() 
        df_display.set_index('record_date', inplace=True)
        
        df_display['空腹状态'] = df_display['fasting'].apply(lambda x: judge_blood_sugar(x, 'fasting'))
        df_display['餐后状态'] = df_display['postprandial'].apply(lambda x: judge_blood_sugar(x, 'postprandial'))
        df_display['睡前状态'] = df_display['bedtime'].apply(lambda x: judge_blood_sugar(x, 'bedtime'))
        
        df_display.rename(columns={'fasting': '空腹数值', 'postprandial': '餐后数值', 'bedtime': '睡前数值'}, inplace=True)
        df_display = df_display[['空腹数值', '空腹状态', '餐后数值', '餐后状态', '睡前数值', '睡前状态']]
        
        st.dataframe(df_display, use_container_width=True)

    else:
        st.info("您的账号暂无记录，请录入数据后查看。")
