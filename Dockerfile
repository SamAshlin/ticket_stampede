FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY seller ./seller

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "seller.main:app", "--host", "0.0.0.0", "--port", "8000"]