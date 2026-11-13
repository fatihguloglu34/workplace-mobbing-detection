from fastapi import FastAPI
from sqlalchemy import create_engine
import pandas as pd
from pydantic import BaseModel


# 1. Veritabanı Bağlantısı (KENDI_SIFREN yazan yeri değiştir)
DB_URL = "mysql+pymysql://root:KENDI_SIFREN@localhost:3306/mobbing_risk"
engine = create_engine(DB_URL)

# API'ye dışarıdan gönderilecek JSON verisinin şablonu
class EmployeeData(BaseModel):
    gorev_sayisi: int
    departman_ortalamasi: float
    yuk_orani: float
    izin_red_orani: float = 0.0 # Şimdilik varsayılan 0

# 2. FastAPI Uygulamasını Başlat
app = FastAPI(title="Mobbing Risk Analizi API")

# 3. İlk Uç Nokta (Endpoint) - Tüm Departmanları Getir
@app.get("/")
def read_root():
    return {"mesaj": "Mobbing API Sistemine Hoş Geldiniz!"}

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
    
    risk_skoru = 0
    risk_durumu = "Düşük Risk"
    
    if data.yuk_orani > 1.5:
        risk_skoru += 50
    if data.izin_red_orani > 0.3:
        risk_skoru += 30
        
    if risk_skoru >= 50:
        risk_durumu = "Yüksek Mobbing Riski (Overload Saptandı)"
        
    return {
        "alinan_veriler": data.dict(),
        "hesaplanan_risk_skoru": risk_skoru,
        "tahmin_sonucu": risk_durumu
    }