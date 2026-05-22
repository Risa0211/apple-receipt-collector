FROM python:3.11-slim

WORKDIR /app

# requirements を先にコピーしてキャッシュ効かせる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリ本体
COPY . .

# Cloud Run は $PORT 環境変数（デフォルト 8080）でリッスンさせる
ENV PORT=8080

CMD exec gunicorn app:app --bind 0.0.0.0:$PORT --timeout 300 --workers 1
