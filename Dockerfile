# 第一階段：用 Node 建前端。package-lock.json 先複製，依賴沒變時 npm ci 這一層可以用快取
FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 第二階段：Python 後端。目錄配置跟 repo 一樣（/app/backend、/app/frontend/dist），
# 後端的 defaultFrontendDir（backend/app/main.py）才找得到前端建置結果
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# 不用 root 執行：萬一服務被攻破，容器內的權限也有限
RUN useradd --create-home --uid 1000 app
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
USER app
EXPOSE 8000
