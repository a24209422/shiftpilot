FROM python:3.13-slim

# 不寫 .pyc；log 不經緩衝直接輸出，docker compose logs 才看得到即時訊息
ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

WORKDIR /app

# 先只複製 requirements.txt：程式碼改了但套件沒變時，這一層沿用快取，不必重新安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 只複製 app 執行需要的檔案，測試、評測和 .env 都不會進映像檔
COPY app.py db.py text2sql.py schema.sql llm_schema.sql ./

# 不用 root 執行：萬一 app 有漏洞被利用，能在容器裡做的事比較少
RUN useradd --create-home appuser
USER appuser

EXPOSE 8501
# gatherUsageStats=false：公司內部系統，不把使用統計送回 Streamlit
# fileWatcherType=none：容器裡的程式要重建映像檔才會更新，監看檔案變動只是在 WSL 上不停輪詢、白耗 CPU
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false", "--server.fileWatcherType=none"]
