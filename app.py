"""排程工具 MVP：Streamlit 介面。執行：streamlit run app.py"""
import os
from datetime import date, datetime, time, timedelta

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

import db
import text2sql

load_dotenv()
dbPath = os.getenv("DB_PATH", "schedule.db")

eventColumnNames = {
  "title": "標題", "category": "分類", "start_at": "開始", "end_at": "結束",
  "resource_name": "資源", "resource_type": "資源種類", "note": "備註",
}
exampleQuestions = [
  "明天有哪些行程？",
  "下週 A 會議室被預約了幾次？",
  "陳大文這兩週排了哪些晚班？",
  "這週每個人各有幾筆排程？",
]


@st.cache_resource
def prepareDb(path):
  # cache_resource 讓建表與塞示範資料只在 server 啟動時跑一次，不會每次互動都重跑
  db.initDb(path)
  db.seedDemoData(path)
  return True


def formatResource(resource):
  return "全部" if resource is None else f"{resource['name']}（{resource['type']}）"


def showEvents(events):
  if not events:
    st.info("這段期間沒有排程。")
    return
  frame = pd.DataFrame(events).drop(columns=["id"]).rename(columns=eventColumnNames)
  st.dataframe(frame, hide_index=True)


st.set_page_config(page_title="排程工具", page_icon="📅", layout="wide")
prepareDb(dbPath)

st.title("排程工具 MVP")
st.caption(f"資料庫：{dbPath}　｜　text2sql 模型：{text2sql.getOllamaConfig()['model']}（Ollama）")

queryTab, listTab, addTab, resourceTab = st.tabs(["自然語言查詢", "排程清單", "新增排程", "資源"])

with queryTab:
  st.write("用中文問排程相關的問題，系統會轉成 SQL 查詢資料庫（唯讀，不會修改資料）。")
  runQuery = False
  for column, example in zip(st.columns(len(exampleQuestions)), exampleQuestions):
    if column.button(example):
      # 範例按鈕要在 text_input 建立前寫入 session_state，否則 Streamlit 會報錯
      st.session_state.question = example
      runQuery = True
  question = st.text_input("問題", key="question", placeholder="例如：明天下午誰有排程？")
  runQuery = st.button("查詢", type="primary") or runQuery

  if runQuery and question.strip():
    with st.spinner("模型產生 SQL 中…"):
      try:
        st.session_state.lastResult = text2sql.answerQuestion(question.strip(), dbPath)
      except requests.RequestException as error:
        st.session_state.lastResult = None
        st.error(f"無法呼叫 Ollama：{error}\n\n請確認 Ollama 已啟動，且已下載 {text2sql.getOllamaConfig()['model']}。")

  # 結果存在 session_state，切換分頁或操作其他元件時才不會消失
  result = st.session_state.get("lastResult")
  if result:
    st.code(result["sql"] or "（模型沒有產生 SQL）", language="sql")
    if result["error"]:
      st.error(f"查詢失敗（嘗試 {result['attempts']} 次）：{result['error']}")
    elif not result["rows"]:
      st.info("查詢成功，但沒有符合的資料。")
    else:
      st.dataframe(pd.DataFrame(result["rows"], columns=result["columns"]), hide_index=True)
    if result["attempts"] > 1 and not result["error"]:
      st.caption(f"第一次產生的 SQL 有錯，模型修正後第 {result['attempts']} 次成功。")

with listTab:
  today = date.today()
  monday = today - timedelta(days=today.weekday())
  filterColumns = st.columns(2)
  dateRange = filterColumns[0].date_input("日期區間", value=(monday, monday + timedelta(days=13)))
  selectedResource = filterColumns[1].selectbox(
    "資源", [None] + db.listResources(dbPath), format_func=formatResource
  )
  if isinstance(dateRange, tuple) and len(dateRange) == 2:
    resourceId = selectedResource["id"] if selectedResource else None
    showEvents(db.listEvents(dbPath, dateRange[0], dateRange[1], resourceId))
  else:
    st.info("請選擇結束日期。")

with addTab:
  resources = db.listResources(dbPath)
  if not resources:
    st.warning("請先到「資源」分頁新增資源。")
  else:
    categories = db.getVocabulary(dbPath)["categories"]
    with st.form("addEventForm"):
      title = st.text_input("標題")
      category = st.text_input("分類", value="meeting", help=f"目前已有：{', '.join(categories)}")
      resource = st.selectbox("資源", resources, format_func=formatResource)
      timeColumns = st.columns(3)
      eventDate = timeColumns[0].date_input("日期", value=date.today())
      startTime = timeColumns[1].time_input("開始", value=time(9, 0), step=timedelta(minutes=15))
      endTime = timeColumns[2].time_input("結束", value=time(10, 0), step=timedelta(minutes=15))
      note = st.text_area("備註")
      submitted = st.form_submit_button("新增", type="primary")

    if submitted:
      if not title.strip() or not category.strip():
        st.error("標題和分類不能空白。")
      else:
        try:
          db.addEvent(
            dbPath, title, category, resource["id"],
            datetime.combine(eventDate, startTime), datetime.combine(eventDate, endTime),
            note or None,
          )
          st.success(f"已新增：{eventDate} {startTime:%H:%M}–{endTime:%H:%M} {title}（{resource['name']}）")
        except db.ScheduleConflictError as error:
          st.error(f"{resource['name']} 在這個時段已經有排程，沒有新增：")
          st.dataframe(pd.DataFrame(error.conflicts).drop(columns=["id"]).rename(columns=eventColumnNames), hide_index=True)
        except ValueError as error:
          st.error(str(error))

with resourceTab:
  st.dataframe(pd.DataFrame(db.listResources(dbPath)), hide_index=True)
  with st.form("addResourceForm", clear_on_submit=True):
    st.write("新增資源")
    name = st.text_input("名稱")
    resourceType = st.text_input("種類", value="person", help="例如 person、room、equipment，也可以自訂")
    submitted = st.form_submit_button("新增")
  if submitted:
    if not name.strip() or not resourceType.strip():
      st.error("名稱和種類不能空白。")
    else:
      db.addResource(dbPath, name, resourceType)
      st.rerun()
