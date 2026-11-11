-- =====================================================================
-- Mobbing Risk Analizi Sistemi: örnek sorgular
--
--   A. Temel sorgular
--   B. Gösterge sorguları (her biri bir mobbing belirtisini ölçer)
--   C. Simülasyonun cevap anahtarı
--   D. Tutarlılık kontrolleri
--
-- Aylık sorgularda ay, ayın ilk günü olarak yazılır (örnek: 2025-03-01);
-- simulation_labels tablosundaki period_month ile aynı biçimdedir.
-- =====================================================================

USE mobbing_risk;

-- ---------------------------------------------------------------------
-- A. TEMEL SORGULAR
-- ---------------------------------------------------------------------

-- A1. Çalışan listesi: departmanı ve yöneticisiyle birlikte
SELECT e.employee_id,
       CONCAT(e.first_name, ' ', e.last_name) AS calisan,
       e.title                                AS unvan,
       d.name                                 AS departman,
       CONCAT(m.first_name, ' ', m.last_name) AS yonetici
FROM employees e
JOIN departments d    ON d.department_id = e.department_id
LEFT JOIN employees m ON m.employee_id = e.manager_id
ORDER BY d.name, e.last_name, e.first_name;

-- A2. Departman başına çalışan sayısı (hâlâ çalışanlar)
SELECT d.name AS departman, COUNT(*) AS calisan_sayisi
FROM employees e
JOIN departments d ON d.department_id = e.department_id
WHERE e.termination_date IS NULL
GROUP BY d.department_id, d.name
ORDER BY calisan_sayisi DESC;

-- A3. Bir yöneticinin ekibi (örnek: 14 numaralı yönetici)
SELECT employee_id, first_name, last_name, title, hire_date, termination_date
FROM employees
WHERE manager_id = 14
ORDER BY last_name, first_name;

-- A4. Bir çalışanın bir aydaki giriş çıkış kayıtları (örnek: 97 numaralı çalışan, Ekim 2025)
SELECT work_date, check_in, check_out
FROM attendance_logs
WHERE employee_id = 97
  AND work_date BETWEEN '2025-10-01' AND '2025-10-31'
ORDER BY work_date;

-- ---------------------------------------------------------------------
-- B. GÖSTERGE SORGULARI
-- ---------------------------------------------------------------------

-- B1. Aylık ek mesai (saat) ve hafta sonu çalışılan gün sayısı.
-- Hafta içi 9 saati aşan süre, hafta sonu ise çalışılan sürenin tamamı ek mesaidir.
SELECT employee_id,
       DATE_FORMAT(work_date, '%Y-%m-01') AS period_month,
       ROUND(SUM(CASE
                   WHEN WEEKDAY(work_date) >= 5 THEN TIME_TO_SEC(TIMEDIFF(check_out, check_in))
                   ELSE GREATEST(TIME_TO_SEC(TIMEDIFF(check_out, check_in)) - 9 * 3600, 0)
                 END) / 3600, 1)          AS ek_mesai_saat,
       SUM(WEEKDAY(work_date) >= 5)       AS hafta_sonu_gun
FROM attendance_logs
GROUP BY employee_id, period_month
ORDER BY ek_mesai_saat DESC
LIMIT 20;

-- B2. Çalışan bazında izin başvurusu ve onay oranı
SELECT e.employee_id,
       CONCAT(e.first_name, ' ', e.last_name) AS calisan,
       COUNT(*)                               AS basvuru,
       SUM(l.status = 'approved')             AS onay,
       SUM(l.status = 'rejected')             AS ret,
       ROUND(SUM(l.status = 'approved') / COUNT(*), 2) AS onay_orani
FROM leave_requests l
JOIN employees e ON e.employee_id = l.employee_id
WHERE l.status <> 'pending'
GROUP BY e.employee_id, calisan
HAVING basvuru >= 3
ORDER BY onay_orani, basvuru DESC
LIMIT 20;

-- B3. Yöneticiye göre izin ret oranı ve ortalama karar süresi (gün)
SELECT m.employee_id                          AS yonetici_id,
       CONCAT(m.first_name, ' ', m.last_name) AS yonetici,
       COUNT(*)                               AS karar,
       SUM(l.status = 'rejected')             AS ret,
       ROUND(SUM(l.status = 'rejected') / COUNT(*), 2) AS ret_orani,
       ROUND(AVG(TIMESTAMPDIFF(HOUR, l.requested_at, l.decided_at)) / 24, 1) AS ortalama_karar_gunu
FROM leave_requests l
JOIN employees m ON m.employee_id = l.decided_by
GROUP BY m.employee_id, yonetici
ORDER BY ret_orani DESC;

-- B4. Departmanın o ayki kişi başı görev ortalamasının 1,5 katından fazla görev alanlar
SELECT c.employee_id,
       c.period_month,
       c.gorev_sayisi,
       ROUND(a.departman_ortalamasi, 1)                   AS departman_ortalamasi,
       ROUND(c.gorev_sayisi / a.departman_ortalamasi, 2)  AS yuk_orani
FROM (
  SELECT t.assigned_to AS employee_id,
         e.department_id,
         DATE_FORMAT(t.assigned_at, '%Y-%m-01') AS period_month,
         COUNT(*) AS gorev_sayisi
  FROM tasks t
  JOIN employees e ON e.employee_id = t.assigned_to
  GROUP BY t.assigned_to, e.department_id, period_month
) c
JOIN (
  SELECT e.department_id,
         DATE_FORMAT(t.assigned_at, '%Y-%m-01') AS period_month,
         COUNT(*) / COUNT(DISTINCT t.assigned_to) AS departman_ortalamasi
  FROM tasks t
  JOIN employees e ON e.employee_id = t.assigned_to
  GROUP BY e.department_id, period_month
) a ON a.department_id = c.department_id AND a.period_month = c.period_month
WHERE c.gorev_sayisi > 1.5 * a.departman_ortalamasi
ORDER BY yuk_orani DESC
LIMIT 20;

-- B5. Çalışan bazında aylık görev özeti:
--   mesai_disi : hafta sonu ya da 19:00 ile 07:00 arasında verilen görev
--   dar_sureli : verildikten sonra 24 saat içinde istenen görev
--   geciken    : teslim tarihinden sonra biten görev
SELECT assigned_to AS employee_id,
       DATE_FORMAT(assigned_at, '%Y-%m-01') AS period_month,
       COUNT(*) AS gorev_sayisi,
       SUM(WEEKDAY(assigned_at) >= 5 OR HOUR(assigned_at) >= 19 OR HOUR(assigned_at) < 7) AS mesai_disi,
       SUM(TIMESTAMPDIFF(HOUR, assigned_at, due_at) <= 24)                                AS dar_sureli,
       SUM(completed_at > due_at)                                                         AS geciken
FROM tasks
GROUP BY assigned_to, period_month
ORDER BY mesai_disi DESC, dar_sureli DESC
LIMIT 20;

-- B6. Kim kime mesai dışında görev veriyor
SELECT t.assigned_by                          AS veren_id,
       CONCAT(b.first_name, ' ', b.last_name) AS veren,
       t.assigned_to                          AS alan_id,
       CONCAT(a.first_name, ' ', a.last_name) AS alan,
       COUNT(*)                               AS mesai_disi_gorev
FROM tasks t
JOIN employees b ON b.employee_id = t.assigned_by
JOIN employees a ON a.employee_id = t.assigned_to
WHERE WEEKDAY(t.assigned_at) >= 5 OR HOUR(t.assigned_at) >= 19 OR HOUR(t.assigned_at) < 7
GROUP BY t.assigned_by, veren, t.assigned_to, alan
HAVING mesai_disi_gorev >= 5
ORDER BY mesai_disi_gorev DESC;

-- B7. Ekip toplantılarından dışlanma.
-- Çalışanın, yöneticisinin düzenlediği ekip toplantılarına çağrılması beklenir.
-- Çağrılmadıysa meeting_participants tablosunda satırı yoktur (LEFT JOIN boş döner).
SELECT e.employee_id,
       CONCAT(e.first_name, ' ', e.last_name)        AS calisan,
       DATE_FORMAT(m.starts_at, '%Y-%m-01')          AS period_month,
       COUNT(*)                                      AS ekip_toplantisi,
       COUNT(p.participant_id)                       AS cagrildigi,
       ROUND(1 - COUNT(p.participant_id) / COUNT(*), 2) AS dislanma_orani
FROM employees e
JOIN meetings m
  ON m.meeting_type = 'team'
 AND m.organizer_id = e.manager_id
 AND DATE(m.starts_at) >= e.hire_date
 AND (e.termination_date IS NULL OR DATE(m.starts_at) <= e.termination_date)
LEFT JOIN meeting_participants p
  ON p.meeting_id = m.meeting_id
 AND p.employee_id = e.employee_id
GROUP BY e.employee_id, calisan, period_month
HAVING ekip_toplantisi >= 3 AND dislanma_orani >= 0.5
ORDER BY dislanma_orani DESC, period_month;

-- B8. Performans puanı bir önceki çeyreğe göre en az 1 puan düşenler
SELECT e.employee_id,
       CONCAT(e.first_name, ' ', e.last_name) AS calisan,
       r2.period_quarter                      AS ceyrek,
       r1.score                               AS onceki_puan,
       r2.score                               AS puan,
       r2.score - r1.score                    AS degisim
FROM performance_reviews r2
JOIN performance_reviews r1
  ON r1.employee_id = r2.employee_id
 AND r1.period_year = r2.period_year
 AND r1.period_quarter = r2.period_quarter - 1
JOIN employees e ON e.employee_id = r2.employee_id
WHERE r2.score - r1.score <= -1
ORDER BY degisim, e.employee_id;

-- B9. Hakkında şikâyet edilenler: şikâyet sayısı ve kaç farklı kişiden geldiği
SELECT c.accused_id,
       CONCAT(e.first_name, ' ', e.last_name) AS sikayet_edilen,
       e.title                                AS unvan,
       COUNT(*)                               AS sikayet_sayisi,
       COUNT(DISTINCT c.reporter_id)          AS farkli_kisi
FROM complaints c
JOIN employees e ON e.employee_id = c.accused_id
GROUP BY c.accused_id, sikayet_edilen, unvan
ORDER BY sikayet_sayisi DESC, farkli_kisi DESC;

-- B10. Son ankette boyut ortalaması 4 ve üzeri olan çalışanlar
-- (puan yükseldikçe çalışan durumu daha olumsuz görüyor demektir)
SELECT a.employee_id,
       q.dimension            AS boyut,
       ROUND(AVG(a.score), 2) AS ortalama
FROM survey_answers a
JOIN survey_questions q ON q.question_id = a.question_id
WHERE q.survey_id = 2
GROUP BY a.employee_id, q.dimension
HAVING ortalama >= 4
ORDER BY a.employee_id, q.dimension;

-- ---------------------------------------------------------------------
-- C. SİMÜLASYONUN CEVAP ANAHTARI
-- ---------------------------------------------------------------------

-- C1. Senaryolar: kime, kim, hangi aylar arasında, hangi yollarla baskı uyguladı
SELECT CONCAT(v.first_name, ' ', v.last_name) AS calisan,
       CONCAT(p.first_name, ' ', p.last_name) AS baski_uygulayan,
       s.start_month,
       s.end_month,
       s.has_overload,
       s.has_exclusion,
       s.has_leave_denial,
       s.has_unfair_evaluation
FROM simulation_scenarios s
JOIN employees v ON v.employee_id = s.employee_id
JOIN employees p ON p.employee_id = s.perpetrator_id
ORDER BY s.start_month, calisan;

-- C2. Veri bölmesi: her bölmede kaç çalışan, kaç çalışan-ay ve kaç mobbing etiketli ay var
SELECT d.split,
       COUNT(DISTINCT d.employee_id) AS calisan,
       COUNT(*)                      AS calisan_ay,
       SUM(l.is_mobbing)             AS mobbing_etiketli_ay
FROM dataset_splits d
JOIN simulation_labels l ON l.employee_id = d.employee_id
GROUP BY d.split;

-- C3. Bir göstergeyi etiketle karşılaştırma: mobbing etiketli aylarda ek mesai ortalaması
SELECT l.is_mobbing,
       COUNT(*)                        AS calisan_ay,
       ROUND(AVG(o.ek_mesai_saat), 1)  AS ortalama_ek_mesai_saat
FROM simulation_labels l
JOIN (
  SELECT employee_id,
         DATE_FORMAT(work_date, '%Y-%m-01') AS period_month,
         SUM(CASE
               WHEN WEEKDAY(work_date) >= 5 THEN TIME_TO_SEC(TIMEDIFF(check_out, check_in))
               ELSE GREATEST(TIME_TO_SEC(TIMEDIFF(check_out, check_in)) - 9 * 3600, 0)
             END) / 3600 AS ek_mesai_saat
  FROM attendance_logs
  GROUP BY employee_id, period_month
) o ON o.employee_id = l.employee_id AND o.period_month = l.period_month
GROUP BY l.is_mobbing;

-- ---------------------------------------------------------------------
-- D. TUTARLILIK KONTROLLERİ (hepsinde hata sayısı 0 çıkmalı)
-- ---------------------------------------------------------------------

SELECT 'Onaylı izin gününde giriş kaydı' AS kontrol, COUNT(*) AS hata
FROM leave_requests l
JOIN attendance_logs a
  ON a.employee_id = l.employee_id
 AND a.work_date BETWEEN l.start_date AND l.end_date
WHERE l.status = 'approved'
UNION ALL
SELECT 'İşe girmeden önce ya da ayrıldıktan sonra giriş kaydı', COUNT(*)
FROM attendance_logs a
JOIN employees e ON e.employee_id = a.employee_id
WHERE a.work_date < e.hire_date OR a.work_date > e.termination_date
UNION ALL
SELECT 'Çıkış saati giriş saatinden önce', COUNT(*)
FROM attendance_logs
WHERE check_out <= check_in
UNION ALL
SELECT 'Biten görevde bitiş zamanı boş ya da bitmeyen görevde dolu', COUNT(*)
FROM tasks
WHERE (status = 'done' AND completed_at IS NULL) OR (status <> 'done' AND completed_at IS NOT NULL)
UNION ALL
SELECT 'Karar verilmiş izinde karar bilgisi eksik ya da bekleyen izinde dolu', COUNT(*)
FROM leave_requests
WHERE (status <> 'pending' AND (decided_by IS NULL OR decided_at IS NULL))
   OR (status = 'pending' AND (decided_by IS NOT NULL OR decided_at IS NOT NULL))
UNION ALL
SELECT 'Kendi kendini değerlendiren', COUNT(*)
FROM performance_reviews
WHERE reviewer_id = employee_id
UNION ALL
SELECT 'Kendini şikâyet eden', COUNT(*)
FROM complaints
WHERE accused_id = reporter_id
UNION ALL
SELECT 'Etiketi 1 olup senaryo dışında kalan ay', COUNT(*)
FROM simulation_labels l
LEFT JOIN simulation_scenarios s
  ON s.employee_id = l.employee_id
 AND l.period_month BETWEEN s.start_month AND s.end_month
WHERE l.is_mobbing = 1 AND s.scenario_id IS NULL
UNION ALL
SELECT 'Senaryo içinde olup etiketi 0 kalan ay', COUNT(*)
FROM simulation_labels l
JOIN simulation_scenarios s
  ON s.employee_id = l.employee_id
 AND l.period_month BETWEEN s.start_month AND s.end_month
WHERE l.is_mobbing = 0
UNION ALL
SELECT 'Veri bölmesi olmayan çalışan', COUNT(*)
FROM employees e
LEFT JOIN dataset_splits d ON d.employee_id = e.employee_id
WHERE d.employee_id IS NULL;
