import os

from fastapi import FastAPI
from sqlalchemy import create_engine
import pandas as pd
from pydantic import BaseModel, Field


# 1. Veritabanı Bağlantısı
# Şifre koda yazılmaz; DB_URL ortam değişkeninden okunur. Örnek:
#   export DB_URL="mysql+pymysql://root:SIFREN@localhost:3306/mobbing_risk"
DB_URL = os.getenv("DB_URL", "mysql+pymysql://root:@localhost:3306/mobbing_risk")
engine = create_engine(DB_URL)

# API'ye dışarıdan gönderilecek JSON verisinin şablonu.
# Negatif değerler kabul edilmez (ge=0), departman ortalaması 0'dan büyük olmalı (gt=0).
class EmployeeData(BaseModel):
    gorev_sayisi: int = Field(ge=0)
    departman_ortalamasi: float = Field(gt=0)
    izin_red_orani: float = Field(default=0.0, ge=0, le=1)  # 0 ile 1 arası oran

# 2. FastAPI Uygulamasını Başlat
app = FastAPI(title="Mobbing Risk Analizi API")

@app.get("/")
def read_root():
    return {"mesaj": "Mobbing API Sistemine Hoş Geldiniz!"}

# 3. Tüm Departmanları Getir
@app.get("/departmanlar")
def get_departments():
    # Veritabanından departmanları çekiyoruz
    query = "SELECT * FROM departments;"
    df = pd.read_sql(query, con=engine)

    # Pandas DataFrame'i JSON (Sözlük) formatına çevirip döndürüyoruz
    return df.to_dict(orient="records")

@app.get("/overload-analizi")
def get_overload_data():
    # Model eğitimi ve iş zekası araçları için Aşırı İş Yükü (Overload) verisini çeken sorgu
    # (03_queries.sql B4 sorgusu; pymysql için % işaretleri %% olarak yazılır)
    query = """
    SELECT c.employee_id,
           c.period_month,
           c.gorev_sayisi,
           ROUND(a.departman_ortalamasi, 1)                   AS departman_ortalamasi,
           ROUND(c.gorev_sayisi / a.departman_ortalamasi, 2)  AS yuk_orani
    FROM (
      SELECT t.assigned_to AS employee_id,
             e.department_id,
             DATE_FORMAT(t.assigned_at, '%%Y-%%m-01') AS period_month,
             COUNT(*) AS gorev_sayisi
      FROM tasks t
      JOIN employees e ON e.employee_id = t.assigned_to
      GROUP BY t.assigned_to, e.department_id, period_month
    ) c
    JOIN (
      SELECT e.department_id,
             DATE_FORMAT(t.assigned_at, '%%Y-%%m-01') AS period_month,
             COUNT(*) / COUNT(DISTINCT t.assigned_to) AS departman_ortalamasi
      FROM tasks t
      JOIN employees e ON e.employee_id = t.assigned_to
      GROUP BY e.department_id, period_month
    ) a ON a.department_id = c.department_id AND a.period_month = c.period_month
    WHERE c.gorev_sayisi > 1.5 * a.departman_ortalamasi
    ORDER BY yuk_orani DESC
    """

    # SQL sorgusunu çalıştırıp sonucu DataFrame'e alıyoruz
    df = pd.read_sql(query, con=engine)

    # Veriyi API üzerinden yayınlanacak formata (JSON) çeviriyoruz
    return df.to_dict(orient="records")

@app.post("/tahmin-et")
def predict_mobbing(data: EmployeeData):
    # Gerçek projede burada "model.predict(veriler)" çalışır.
    # Şimdilik model yokmuş gibi kural tabanlı bir simülasyon yapıyoruz:

    # Yük oranı, /overload-analizi ile aynı şekilde hesaplanır
    yuk_orani = round(data.gorev_sayisi / data.departman_ortalamasi, 2)

    risk_skoru = 0
    if yuk_orani > 1.5:
        risk_skoru += 50
    if data.izin_red_orani > 0.3:
        risk_skoru += 30

    # Seviyeler risk_assessments.risk_level ile aynı: low / medium / high
    if risk_skoru >= 50:
        risk_seviyesi = "high"
        risk_durumu = "Yüksek Mobbing Riski"
    elif risk_skoru >= 30:
        risk_seviyesi = "medium"
        risk_durumu = "Orta Mobbing Riski"
    else:
        risk_seviyesi = "low"
        risk_durumu = "Düşük Risk"

    return {
        "alinan_veriler": data.model_dump(),
        "yuk_orani": yuk_orani,
        "hesaplanan_risk_skoru": risk_skoru,
        "risk_seviyesi": risk_seviyesi,
        "tahmin_sonucu": risk_durumu
    }
