import streamlit as st
import pandas as pd
import datetime
from sqlalchemy import text

# ==========================================
# 1. 云端数据库核心操作 (基于 PostgreSQL)
# ==========================================
conn = st.connection("supabase", type="sql")

def init_db():
    with conn.session as s:
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS glucose_logs (
                record_date DATE PRIMARY KEY,
                fasting NUMERIC,
                postprandial NUMERIC,
                bedtime NUMERIC
            );
        '''))
        s.commit()

def save_to_db(date, fasting, postprandial, bedtime):
    with conn.session as s:
        s.execute(text('''
            INSERT INTO glucose_logs (record_date, fasting, postprandial, bedtime)
            VALUES (:date, :fasting, :postprandial, :bedtime)
            ON CONFLICT (record_date) DO UPDATE SET
                fasting = EXCLUDED.fasting,
                postprandial = EXCLUDED.postprandial,
                bedtime = EXCLUDED.bedtime;
        '''), {"date": date, "fasting": fasting, "postprandial": postprandial, "bedtime": bedtime})
        s.commit()

def load_from_db():
    df = conn.query("SELECT * FROM glucose_logs ORDER BY record_date ASC", ttl=0)
    return df

init_db()

# ==========================================
# 2. 软件界面与交互逻辑
# ==========================================
st.set_page_config(page_title="血糖监测与分析系统", layout="centered")
st.title("🩸 个人血糖监测软件 (云端版)")

st.header("1. 录入今日或历史数据")

selected_date = st.date_input("请选择日期", datetime.date.today())

col1, col2, col3 = st.columns(3)
with col1:
    fasting_val = st.number_input("空腹血糖 (mmol/L)", min_value=0.0, max_value=35.0, step=0.1, format="%.1f")
with col2:
    postprandial_val = st.number_input("餐后2h血糖 (mmol/L)", min_value=0.0, max_value=35.0, step=0.1, format="%.1f")
with col3:
    bedtime_val = st.number_input("睡前血糖 (mmol/L)", min_value=0.0, max_value=35.0, step=0.1, format="%.1f")

if st.button("同步至云端"):
    save_to_db(selected_date, fasting_val, postprandial_val, bedtime_val)
    st.success(f"{selected_date} 的数据已安全同步至云端数据库！")

st.divider()
st.header("2. 数据分析曲线")

df_records = load_from_db()

if not df_records.empty:
    df_records['record_date'] = pd.to_datetime(df_records['record_date'])
    df_records.set_index('record_date', inplace=True)
    
    df_records.rename(columns={
        'fasting': '空腹血糖',
        'postprandial': '餐后2h血糖',
        'bedtime': '睡前血糖'
    }, inplace=True)
    
    st.subheader("云端数据记录表")
    st.dataframe(df_records, use_container_width=True)
    
    st.subheader("血糖波动趋势图")
    st.line_chart(df_records)
else:
    st.info("云端数据库暂无数据。请录入并同步后查看分析曲线。")
