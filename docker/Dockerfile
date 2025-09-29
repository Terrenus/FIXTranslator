FROM python:3.11-slim
WORKDIR /app
COPY ../requirements.txt /app/requirements.txt
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 9000
CMD ["uvicorn","fixparser.main:app","--host","0.0.0.0","--port","9000"]
