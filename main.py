import streamlit as st
import pandas as pd
import datetime
from sqlalchemy import text
import plotly.express as px
import requests
import json
import extra_streamlit_components as stx # 新增：引入 Cookie 管理器

# ==========================================
# 0. 动态云端引擎：调用 ChatAnywhere (OpenAI 代理) API 查询 GI
# ==========================================
def fetch_gi_from_ai(food_name):
    api_key = st.secrets.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "⚠️ API Key 未配置，请在 Streamlit Secrets 中设置 OPENAI_API_KEY。"}

    url = "https://api.chatanywhere.tech/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    system_prompt = """
    你是一个严谨的临床营养学专家。用户会输入一种食物名称。
    请你查询或估算该食物的升糖指数(GI值)，并严格以JSON格式返回。
    必须包含以下4个字段：
    {"food": "食物标准名称", "gi": 具体数字, "level": "低GI 🟢/中GI 🟡/高GI 🔴 (低于55为低，55-70为中，高于70为高)", "advice": "一句简短的针对高血糖人群的食用建议"}
    """
    
    payload = {
        "model": "gpt-3.5-turbo", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请查阅食物：{food_name}"}
        ],
        "temperature": 0.1,
        "response_format": { "type": "json_object" } 
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status() 
        result = response.json()
        ai_content = result['choices'][0]['message']['content']
        data = json.loads(ai_content)
        return data
    except Exception as e:
        return {"error": f"查询失败，请检查网络或 API Key：{str(e)}"}

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

def judge_blood_sugar(value, time_type):
    if pd.isna(value) or value == 0.0 or value is None:
        return "未录入 ⚪"
    if time_type == 'fasting': 
        if value < 4.4: return "偏低 🔵"
        elif value <= 7.0: return "正常 🟢"
        else: return "偏高 🔴"
    elif time_type == 'postprandial': 
        if value < 4.4: return "偏低 🔵"
        elif value <= 10.0: return "正常 🟢"
        else: return "偏高 🔴"
    elif time_type == 'bedtime': 
        if value < 4.4: return "偏低 🔵"
        elif value <= 11.0: return "正常 🟢"
        else: return "偏高 🔴"
    return "未知"

# ==========================================
# 4. 前端界面展示 (引入 Cookie 记忆逻辑)
# ==========================================
st.set_page_config(page_title="血糖监测与分析系统", layout="centered", page_icon="🩸")

# 启动 Cookie 管理器
cookie_manager = stx.CookieManager()

# 核心逻辑：系统启动时，先去浏览器 Cookie 里翻找有没有历史登录记录
if "logged_in_user" not in st.session_state:
    cached_user = cookie_manager.get(cookie="saved_username")
    if cached_user:
        st.session_state["logged_in_user"] = cached_user # 找到凭证，自动免密登录
    else:
        st.session_state["logged_in_user"] = None

# 未登录状态的界面
if st.session_state["logged_in_user"] is None:
    st.title("🔐 血糖监测系统 - 登录")
    
    tab1, tab2 = st.tabs(["🔑 登录", "📝 注册账号"])
    
    with tab1:
        st.subheader("账号登录")
        login_u = st.text_input("用户名", key="login_u")
        login_p = st.text_input("密码", type="password", key="login_p")
        
        # 新增：记住密码勾选项
        remember_me = st.checkbox("保持登录 (7天内免输密码)")
        
        if st.button("登录", use_container_width=True):
            if verify_login(login_u, login_p):
                st.session_state["logged_in_user"] = login_u
                
                # 如果勾选了记住密码，发放时长 7 天的 Cookie 凭证
                if remember_me:
                    expire_date = datetime.datetime.now() + datetime.timedelta(days=7)
                    cookie_manager.set("saved_username", login_u, expires_at=expire_date)
                    
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

# 已登录状态的主系统界面
else:
    current_user = st.session_state["logged_in_user"]
    
    st.sidebar.title("用户信息")
    st.sidebar.info(f"当前登录：**{current_user}**")
    
    # 退出登录时，同时销毁 Cookie 凭证
    if st.sidebar.button("退出登录"):
        st.session_state["logged_in_user"] = None
        cookie_manager.delete("saved_username")
        st.rerun()
        
    st.sidebar.divider()
    
    st.sidebar.title("🤖 AI 食物 GI 速查")
    st.sidebar.caption("接入 OpenAI 智能分析模型，查询天下万物。")
    search_query = st.sidebar.text_input("想吃什么？输入名称 (如: 兰州拉面, 拿铁)")
    
    if st.sidebar.button("启动 AI 分析"):
        if search_query:
            with st.sidebar.status(f"正在呼叫云端 AI 分析【{search_query}】...", expanded=True) as status:
                ai_data = fetch_gi_from_ai(search_query)
                status.update(label="分析完成！", state="complete", expanded=False)
            if "error" in ai_data:
                st.sidebar.error(ai_data["error"])
            else:
                st.sidebar.success(f"匹配成功：{ai_data.get('food', search_query)}")
                st.sidebar.metric("预估 GI 指数", ai_data.get('gi', '未知'))
                st.sidebar.markdown(f"**评级**: {ai_data.get('level', '未知')}")
                st.sidebar.markdown(f"💡 **专家建议**: {ai_data.get('advice', '暂无建议')}")
        else:
            st.sidebar.warning("请先输入食物名称哦！")
    
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

    df_records = load_from_db(current_user)

    if not df_records.empty:
        df_records['record_date'] = pd.to_datetime(df_records['record_date'])
        df_plot = df_records.copy()
        df_plot[['fasting', 'postprandial', 'bedtime']] = df_plot[['fasting', 'postprandial', 'bedtime']].replace(0.0, None)

        st.header("2. 数据执行摘要 (Executive Summary)")
        total_days = len(df_plot)
        
        v_fasting = df_plot['fasting'].dropna()
        f_avg = v_fasting.mean() if not v_fasting.empty else 0
        f_std = v_fasting.std() if len(v_fasting) > 1 else 0
        f_tir = (v_fasting.apply(lambda x: 4.4 <= x <= 7.0).sum() / len(v_fasting)) * 100 if not v_fasting.empty else 0

        v_post = df_plot['postprandial'].dropna()
        p_avg = v_post.mean() if not v_post.empty else 0
        p_std = v_post.std() if len(v_post) > 1 else 0
        p_tir = (v_post.apply(lambda x: 4.4 <= x <= 10.0).sum() / len(v_post)) * 100 if not v_post.empty else 0

        v_bed = df_plot['bedtime'].dropna()
        b_avg = v_bed.mean() if not v_bed.empty else 0
        b_std = v_bed.std() if len(v_bed) > 1 else 0
        b_tir = (v_bed.apply(lambda x: 4.4 <= x <= 11.0).sum() / len(v_bed)) * 100 if not v_bed.empty else 0

        st.markdown(f"**总活跃天数**: `{total_days} 天`")
        
        tab_f, tab_p, tab_b = st.tabs(["🌅 空腹监控", "🍽️ 餐后2h监控", "🌙 睡前监控"])
        
        with tab_f:
            if not v_fasting.empty:
                col1, col2, col3 = st.columns(3)
                col1.metric("均值 (mmol/L)", f"{f_avg:.2f}", "目标 ≤7.0", delta_color="inverse")
                col2.metric("达标率 (TIR)", f"{f_tir:.1f}%")
                col3.metric("波动率 (标准差)", f"{f_std:.2f}")
            else:
                st.info("暂无有效空腹记录")
                
        with tab_p:
            if not v_post.empty:
                col1, col2, col3 = st.columns(3)
                col1.metric("均值 (mmol/L)", f"{p_avg:.2f}", "目标 ≤10.0", delta_color="inverse")
                col2.metric("达标率 (TIR)", f"{p_tir:.1f}%")
                col3.metric("波动率 (标准差)", f"{p_std:.2f}")
            else:
                st.info("暂无有效餐后记录")

        with tab_b:
            if not v_bed.empty:
                col1, col2, col3 = st.columns(3)
                col1.metric("均值 (mmol/L)", f"{b_avg:.2f}", "目标 ≤11.0", delta_color="inverse")
                col2.metric("达标率 (TIR)", f"{b_tir:.1f}%")
                col3.metric("波动率 (标准差)", f"{b_std:.2f}")
            else:
                st.info("暂无有效睡前记录")

        if not v_fasting.empty and not v_post.empty and not v_bed.empty:
            composite_score = (f_tir * 0.5) + (p_tir * 0.3) + (b_tir * 0.2)
            insight_text = f"**系统洞察报告**：全维度数据监控已启动。基于历史记录，您的综合控制达标指数为 **{composite_score:.1f}/100**。 "
            if composite_score >= 85:
                insight_text += "各项波动率极低，整体处于高质量平稳区间。"
            elif composite_score >= 60:
                insight_text += "基本面稳定，但需通过上方标签页核查哪一时间段的【波动率(标准差)】偏高，以规避异常风险。"
            else:
                insight_text += "综合达标率偏低，多因子偏离基准线，建议结合左侧【🤖 AI 食物速查】干预饮食结构。"
            st.info(insight_text)

        st.divider()

        st.header("3. 数据分析曲线")
        
        csv_data = df_records.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 一键导出全部历史数据 (Excel CSV)",
            data=csv_data,
            file_name=f"{current_user}_专属血糖数据.csv",
            mime="text/csv",
            use_container_width=True
        )

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
            xaxis=dict(title="日期", rangeslider=dict(visible=True), type="date"),
            yaxis=dict(title="血糖 (mmol/L)"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=0, r=0, t=30, b=0)
        )
        
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
