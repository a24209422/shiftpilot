"""排程工具 MVP：Streamlit 介面。執行：streamlit run app.py"""
import os
from datetime import date, datetime, time, timedelta

import pandas as pd
import psycopg
import requests
import streamlit as st
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

import db
import text2sql

load_dotenv()
databaseUrl = os.getenv("DATABASE_URL")

eventColumnNames = {
  "title": "標題", "category": "分類", "start_at": "開始", "end_at": "結束",
  "resource_names": "資源", "resource_name": "資源", "note": "備註",
}
exampleQuestions = [
  "明天有哪些行程？",
  "下週 A 會議室被預約了幾次？",
  "陳大文這兩週排了哪些晚班？",
  "這週每個人各有幾筆排程？",
]


@st.cache_resource
def prepareDb(url):
  # cache_resource 讓建表與塞示範資料只在 server 啟動時跑一次，不會每次互動都重跑
  db.initDb(url)
  db.seedDemoData(url)
  return True


def describeDatabase(url):
  # 畫面上只顯示資料庫位置，連線字串裡有密碼，不能整串印出來
  info = conninfo_to_dict(url)
  return f"{info.get('dbname', '')}@{info.get('host', 'localhost')}:{info.get('port', '5432')}"


def formatResource(resource):
  return "全部" if resource is None else f"{resource['name']}（{resource['type']}）"


def showEvents(events):
  if not events:
    st.info("這段期間沒有排程。")
    return
  frame = pd.DataFrame(events).drop(columns=["id"])
  # 一筆排程可能有多個資源，合併成一格才不會讓同一場會議佔好幾列
  frame["resource_names"] = frame["resource_names"].str.join("、")
  st.dataframe(frame.rename(columns=eventColumnNames), hide_index=True)


st.set_page_config(page_title="排程工具", page_icon="📅", layout="wide")
if not databaseUrl:
  st.error("請先在 .env 設定 DATABASE_URL（參考 .env.example）。")
  st.stop()
try:
  prepareDb(databaseUrl)
except psycopg.OperationalError as error:
  st.error(f"無法連線到 PostgreSQL：{error}\n\n請確認已執行 `docker compose up -d`，且 .env 的密碼正確。")
  st.stop()

st.title("排程工具 MVP")
st.caption(f"資料庫：{describeDatabase(databaseUrl)}（PostgreSQL）")

queryTab, listTab, addTab, resourceTab = st.tabs(["自然語言查詢", "排程清單", "新增排程", "資源"])

with queryTab:
  st.write("用中文問排程相關的問題，系統會轉成 SQL 查詢資料庫（唯讀，不會修改資料）。")
  models = text2sql.listModels()
  selectedModel = st.selectbox(
    "模型", models, index=models.index(text2sql.getOllamaConfig()["model"]), format_func=text2sql.describeModel
  )
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
        st.session_state.lastResult = text2sql.answerQuestion(
          question.strip(), databaseUrl, llm=text2sql.getLlm(selectedModel)
        )
      except requests.RequestException as error:
        st.session_state.lastResult = None
        st.error(text2sql.describeLlmError(error, selectedModel))

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
    "資源", [None] + db.listResources(databaseUrl), format_func=formatResource
  )
  if isinstance(dateRange, tuple) and len(dateRange) == 2:
    resourceId = selectedResource["id"] if selectedResource else None
    showEvents(db.listEvents(databaseUrl, dateRange[0], dateRange[1], resourceId))
  else:
    st.info("請選擇結束日期。")

with addTab:
  resources = db.listResources(databaseUrl)
  if not resources:
    st.warning("請先到「資源」分頁新增資源。")
  else:
    categories = db.getVocabulary(databaseUrl)["categories"]
    # multiselect 的選項用 id 而不是整個 dict：dict 不能雜湊，Streamlit 比對已選項目時會出問題
    resourceById = {resource["id"]: resource for resource in resources}
    with st.form("addEventForm"):
      title = st.text_input("標題")
      category = st.text_input("分類", value="meeting", help=f"目前已有：{', '.join(categories)}")
      selectedResourceIds = st.multiselect(
        "資源（可多選，例如參加的人加上會議室）", list(resourceById),
        format_func=lambda resourceId: formatResource(resourceById[resourceId]),
      )
      timeColumns = st.columns(3)
      eventDate = timeColumns[0].date_input("日期", value=date.today())
      startTime = timeColumns[1].time_input("開始", value=time(9, 0), step=timedelta(minutes=15))
      endTime = timeColumns[2].time_input("結束", value=time(10, 0), step=timedelta(minutes=15))
      note = st.text_area("備註")
      submitted = st.form_submit_button("新增", type="primary")

    if submitted:
      if not title.strip() or not category.strip():
        st.error("標題和分類不能空白。")
      elif not selectedResourceIds:
        st.error("至少要選一個資源。")
      else:
        resourceLabel = "、".join(resourceById[resourceId]["name"] for resourceId in selectedResourceIds)
        try:
          db.addEvent(
            databaseUrl, title, category, selectedResourceIds,
            datetime.combine(eventDate, startTime), datetime.combine(eventDate, endTime),
            note or None,
          )
          st.success(f"已新增：{eventDate} {startTime:%H:%M}–{endTime:%H:%M} {title}（{resourceLabel}）")
        except db.ScheduleConflictError as error:
          st.error("下列資源在這個時段已經有排程，整筆都沒有新增：")
          st.dataframe(pd.DataFrame(error.conflicts).drop(columns=["id"]).rename(columns=eventColumnNames), hide_index=True)
        except ValueError as error:
          st.error(str(error))

with resourceTab:
  st.dataframe(pd.DataFrame(db.listResources(databaseUrl)), hide_index=True)
  with st.form("addResourceForm", clear_on_submit=True):
    st.write("新增資源")
    name = st.text_input("名稱")
    resourceType = st.text_input("種類", value="person", help="例如 person、room、equipment，也可以自訂")
    submitted = st.form_submit_button("新增")
  if submitted:
    if not name.strip() or not resourceType.strip():
      st.error("名稱和種類不能空白。")
    else:
      db.addResource(databaseUrl, name, resourceType)
      st.rerun()
