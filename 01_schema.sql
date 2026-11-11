-- =====================================================================
-- Mobbing Risk Analizi Sistemi: veritabanı şeması (MySQL 8)
--
-- Çalıştırma sırası:
--   01_schema.sql   tablolar
--   02_seed.sql     örnek şirket verisi (2025 yılı simülasyonu)
--   03_queries.sql  örnek sorgular
--
-- Tablolar altı grupta toplanır:
--   1. Organizasyon : departments, employees
--   2. Zaman        : attendance_logs, leave_requests
--   3. İş           : employee_requests, tasks, task_changes, meetings,
--                     meeting_participants
--   4. Değerlendirme: feedback_events, performance_reviews, complaints
--   5. Anket        : surveys, survey_questions, survey_answers
--   6. Analiz       : risk_assessments, simulation_scenarios,
--                     simulation_labels, dataset_splits
-- =====================================================================

CREATE DATABASE IF NOT EXISTS mobbing_risk
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE mobbing_risk;

-- ---------------------------------------------------------------------
-- 1. ORGANİZASYON
-- ---------------------------------------------------------------------

CREATE TABLE departments (
  department_id INT         NOT NULL AUTO_INCREMENT,
  name          VARCHAR(80) NOT NULL,
  PRIMARY KEY (department_id),
  UNIQUE (name)
);

-- Çalışanlar. manager_id aynı tabloya bakar: yönetici de bir çalışandır.
-- Çalışan silinmez; işten ayrılınca termination_date doldurulur.
CREATE TABLE employees (
  employee_id      INT          NOT NULL AUTO_INCREMENT,
  first_name       VARCHAR(50)  NOT NULL,
  last_name        VARCHAR(50)  NOT NULL,
  email            VARCHAR(120) NOT NULL,
  gender           ENUM('F','M') NOT NULL,
  birth_date       DATE         NOT NULL,
  hire_date        DATE         NOT NULL,
  termination_date DATE         NULL,
  title            VARCHAR(60)  NOT NULL,
  department_id    INT          NOT NULL,
  manager_id       INT          NULL,
  PRIMARY KEY (employee_id),
  UNIQUE (email),
  FOREIGN KEY (department_id) REFERENCES departments (department_id),
  FOREIGN KEY (manager_id)    REFERENCES employees (employee_id)
);

-- ---------------------------------------------------------------------
-- 2. ZAMAN: giriş çıkış ve izin
-- ---------------------------------------------------------------------

-- Günlük giriş çıkış kaydı. Bir çalışanın bir güne tek kaydı olur.
-- Standart mesai 09:00 ile 18:00 arasıdır (1 saat mola dahil 9 saat);
-- bunu aşan süre ve hafta sonu çalışması ek mesaidir.
CREATE TABLE attendance_logs (
  attendance_id INT  NOT NULL AUTO_INCREMENT,
  employee_id   INT  NOT NULL,
  work_date     DATE NOT NULL,
  check_in      TIME NOT NULL,
  check_out     TIME NOT NULL,
  PRIMARY KEY (attendance_id),
  UNIQUE (employee_id, work_date),
  FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
);

-- İzin başvuruları. Karar verilince status değişir, decided_by ve decided_at dolar.
--   leave_type: annual yıllık, excuse mazeret, sick hastalık, unpaid ücretsiz
CREATE TABLE leave_requests (
  leave_request_id INT          NOT NULL AUTO_INCREMENT,
  employee_id      INT          NOT NULL,
  leave_type       ENUM('annual','excuse','sick','unpaid') NOT NULL,
  start_date       DATE         NOT NULL,
  end_date         DATE         NOT NULL,
  requested_at     DATETIME     NOT NULL,
  status           ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  decided_by       INT          NULL,
  decided_at       DATETIME     NULL,
  decision_note    VARCHAR(255) NULL,
  PRIMARY KEY (leave_request_id),
  FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
  FOREIGN KEY (decided_by)  REFERENCES employees (employee_id),
  CHECK (end_date >= start_date)
);

-- ---------------------------------------------------------------------
-- 3. İŞ: talepler, görevler ve toplantılar
-- ---------------------------------------------------------------------

-- Çalışanın başka bir çalışandan istediği bilgi, onay, kaynak veya planlama desteği.
-- Görülme, ilk yanıt ve sonuç zamanları ayrı tutulur; böylece cevapsız bırakılma
-- ve ekip arkadaşlarına göre seçici geciktirme ölçülebilir.
CREATE TABLE employee_requests (
  request_id        INT      NOT NULL AUTO_INCREMENT,
  requester_id      INT      NOT NULL,
  recipient_id      INT      NOT NULL,
  request_type      ENUM('information','approval','resource','schedule','other') NOT NULL,
  priority          ENUM('low','medium','high') NOT NULL DEFAULT 'medium',
  created_at        DATETIME NOT NULL,
  seen_at           DATETIME NULL,
  first_response_at DATETIME NULL,
  resolved_at       DATETIME NULL,
  outcome           ENUM('approved','rejected','partial','no_action') NULL,
  PRIMARY KEY (request_id),
  FOREIGN KEY (requester_id) REFERENCES employees (employee_id),
  FOREIGN KEY (recipient_id) REFERENCES employees (employee_id),
  CHECK (requester_id <> recipient_id),
  CHECK (seen_at IS NULL OR seen_at >= created_at),
  CHECK (first_response_at IS NULL OR first_response_at >= created_at),
  CHECK (resolved_at IS NULL OR resolved_at >= created_at),
  CHECK ((resolved_at IS NULL AND outcome IS NULL) OR (resolved_at IS NOT NULL AND outcome IS NOT NULL))
);

-- Görevler: kime verildi, kim verdi, ne zaman verildi, ne zaman istendi, ne zaman bitti.
-- Biten görevde status 'done' olur ve completed_at dolar.
CREATE TABLE tasks (
  task_id         INT          NOT NULL AUTO_INCREMENT,
  title           VARCHAR(150) NOT NULL,
  assigned_to     INT          NOT NULL,
  assigned_by     INT          NOT NULL,
  assigned_at     DATETIME     NOT NULL,
  due_at          DATETIME     NOT NULL,
  completed_at    DATETIME     NULL,
  priority        ENUM('low','medium','high','urgent') NOT NULL DEFAULT 'medium',
  estimated_hours DECIMAL(4,1) NOT NULL,
  actual_hours    DECIMAL(5,1) NULL,
  status          ENUM('open','in_progress','done','cancelled') NOT NULL DEFAULT 'open',
  PRIMARY KEY (task_id),
  FOREIGN KEY (assigned_to) REFERENCES employees (employee_id),
  FOREIGN KEY (assigned_by) REFERENCES employees (employee_id),
  CHECK (due_at > assigned_at),
  CHECK (actual_hours IS NULL OR actual_hours > 0)
);

-- Görev verildikten sonra yapılan baskı yaratabilecek değişiklikler.
-- old_due_at ve new_due_at yalnızca son tarih değişikliklerinde dolar.
CREATE TABLE task_changes (
  task_change_id INT      NOT NULL AUTO_INCREMENT,
  task_id        INT      NOT NULL,
  changed_by     INT      NOT NULL,
  change_type    ENUM('deadline_shortened','deadline_extended','priority_increased','reassigned') NOT NULL,
  old_due_at     DATETIME NULL,
  new_due_at     DATETIME NULL,
  changed_at     DATETIME NOT NULL,
  PRIMARY KEY (task_change_id),
  FOREIGN KEY (task_id)    REFERENCES tasks (task_id) ON DELETE CASCADE,
  FOREIGN KEY (changed_by) REFERENCES employees (employee_id),
  CHECK ((change_type IN ('deadline_shortened','deadline_extended') AND old_due_at IS NOT NULL AND new_due_at IS NOT NULL)
      OR (change_type IN ('priority_increased','reassigned') AND old_due_at IS NULL AND new_due_at IS NULL))
);

-- Toplantılar.
--   team       : yöneticinin kendi ekibiyle yaptığı haftalık toplantı
--   department : departmanın aylık toplantısı
--   project    : konuya göre seçilen kişilerle yapılan toplantı
--   company    : bütün şirketin katıldığı aylık toplantı
CREATE TABLE meetings (
  meeting_id       INT          NOT NULL AUTO_INCREMENT,
  title            VARCHAR(150) NOT NULL,
  meeting_type     ENUM('team','department','project','company') NOT NULL,
  organizer_id     INT          NOT NULL,
  starts_at        DATETIME     NOT NULL,
  duration_minutes INT          NOT NULL,
  PRIMARY KEY (meeting_id),
  FOREIGN KEY (organizer_id) REFERENCES employees (employee_id)
);

-- Toplantıya davet edilenler: çalışan ile toplantı arasındaki çoka çok ilişki.
-- Satır varsa kişi davet edilmiştir; attended katılıp katılmadığını söyler.
-- Ekip toplantısına çağrılmayan ekip üyesinin burada satırı olmaz.
CREATE TABLE meeting_participants (
  participant_id   INT      NOT NULL AUTO_INCREMENT,
  meeting_id       INT      NOT NULL,
  employee_id      INT      NOT NULL,
  invited_at       DATETIME NOT NULL,
  responded_at     DATETIME NULL,
  removed_at       DATETIME NULL,
  invitation_status ENUM('invited','accepted','declined','removed') NOT NULL DEFAULT 'invited',
  attended         BOOLEAN  NOT NULL DEFAULT FALSE,
  PRIMARY KEY (participant_id),
  UNIQUE (meeting_id, employee_id),
  FOREIGN KEY (meeting_id)  REFERENCES meetings (meeting_id) ON DELETE CASCADE,
  FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
  CHECK (responded_at IS NULL OR responded_at >= invited_at),
  CHECK (removed_at IS NULL OR removed_at >= invited_at),
  CHECK ((invitation_status = 'removed' AND removed_at IS NOT NULL)
      OR (invitation_status <> 'removed' AND removed_at IS NULL))
);

-- ---------------------------------------------------------------------
-- 4. DEĞERLENDİRME: performans ve şikâyet
-- ---------------------------------------------------------------------

-- Günlük geri bildirim olayı. Tür kadar geri bildirimin özel mi yoksa ekip
-- önünde mi verildiği de tutulur; tek bir olaydan çok tekrar eden örüntü önemlidir.
CREATE TABLE feedback_events (
  feedback_id   INT      NOT NULL AUTO_INCREMENT,
  employee_id   INT      NOT NULL,
  given_by      INT      NOT NULL,
  feedback_type ENUM('praise','correction','warning','criticism') NOT NULL,
  visibility    ENUM('private','team','department') NOT NULL DEFAULT 'private',
  created_at    DATETIME NOT NULL,
  PRIMARY KEY (feedback_id),
  FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
  FOREIGN KEY (given_by)    REFERENCES employees (employee_id),
  CHECK (employee_id <> given_by)
);

-- Çeyreklik performans değerlendirmesi. Puan 1.0 ile 5.0 arasındadır.
CREATE TABLE performance_reviews (
  review_id      INT          NOT NULL AUTO_INCREMENT,
  employee_id    INT          NOT NULL,
  reviewer_id    INT          NOT NULL,
  period_year    INT          NOT NULL,
  period_quarter INT          NOT NULL,
  score          DECIMAL(2,1) NOT NULL,
  comment        VARCHAR(500) NULL,
  reviewed_at    DATE         NOT NULL,
  PRIMARY KEY (review_id),
  UNIQUE (employee_id, period_year, period_quarter),
  FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
  FOREIGN KEY (reviewer_id) REFERENCES employees (employee_id),
  CHECK (period_quarter BETWEEN 1 AND 4),
  CHECK (score BETWEEN 1.0 AND 5.0)
);

-- Çalışanın bildirdiği olumsuz olay. accused_id boş olabilir (kişi belirtilmemiş).
--   category: overload aşırı iş yükü, exclusion dışlama, rights hakların kullandırılmaması,
--             unfair_evaluation haksız değerlendirme, verbal sözlü saldırı, other diğer
CREATE TABLE complaints (
  complaint_id INT      NOT NULL AUTO_INCREMENT,
  reporter_id  INT      NOT NULL,
  accused_id   INT      NULL,
  category     ENUM('overload','exclusion','rights','unfair_evaluation','verbal','other') NOT NULL,
  occurred_on  DATE     NOT NULL,
  reported_at  DATETIME NOT NULL,
  description  TEXT     NOT NULL,
  status       ENUM('open','investigating','resolved','dismissed') NOT NULL DEFAULT 'open',
  is_anonymous BOOLEAN  NOT NULL DEFAULT FALSE,
  PRIMARY KEY (complaint_id),
  FOREIGN KEY (reporter_id) REFERENCES employees (employee_id),
  FOREIGN KEY (accused_id)  REFERENCES employees (employee_id)
);

-- ---------------------------------------------------------------------
-- 5. ANKET
-- ---------------------------------------------------------------------

CREATE TABLE surveys (
  survey_id   INT          NOT NULL AUTO_INCREMENT,
  title       VARCHAR(150) NOT NULL,
  description VARCHAR(500) NULL,
  opens_on    DATE         NOT NULL,
  closes_on   DATE         NOT NULL,
  PRIMARY KEY (survey_id),
  CHECK (closes_on >= opens_on)
);

-- Anket soruları. Bütün sorular olumsuz ifadedir ve 1 ile 5 arasında puanlanır
-- (1 hiç katılmıyorum, 5 tamamen katılıyorum): puan yükseldikçe risk artar.
--   dimension: sorunun ölçtüğü boyut (iş yükü, dışlanma, haklar, adalet, saygı)
CREATE TABLE survey_questions (
  question_id    INT          NOT NULL AUTO_INCREMENT,
  survey_id      INT          NOT NULL,
  question_order INT          NOT NULL,
  question_text  VARCHAR(300) NOT NULL,
  dimension      ENUM('workload','exclusion','rights','fairness','respect') NOT NULL,
  PRIMARY KEY (question_id),
  UNIQUE (survey_id, question_order),
  FOREIGN KEY (survey_id) REFERENCES surveys (survey_id) ON DELETE CASCADE
);

-- Bir çalışanın bir soruya verdiği puan. Çalışan aynı soruyu bir kez yanıtlar.
CREATE TABLE survey_answers (
  answer_id   INT      NOT NULL AUTO_INCREMENT,
  question_id INT      NOT NULL,
  employee_id INT      NOT NULL,
  score       INT      NOT NULL,
  answered_at DATETIME NOT NULL,
  PRIMARY KEY (answer_id),
  UNIQUE (question_id, employee_id),
  FOREIGN KEY (question_id) REFERENCES survey_questions (question_id) ON DELETE CASCADE,
  FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
  CHECK (score BETWEEN 1 AND 5)
);

-- ---------------------------------------------------------------------
-- 6. ANALİZ
-- ---------------------------------------------------------------------

-- Backend'in ürettiği risk analizi sonuçları. Başlangıçta boştur.
-- period_month ayın ilk günüdür (örnek: 2025-03-01).
CREATE TABLE risk_assessments (
  assessment_id INT          NOT NULL AUTO_INCREMENT,
  employee_id   INT          NOT NULL,
  period_month  DATE         NOT NULL,
  risk_score    DECIMAL(5,2) NOT NULL,
  risk_level    ENUM('low','medium','high') NOT NULL,
  llm_report    TEXT         NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (assessment_id),
  UNIQUE (employee_id, period_month),
  FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
  CHECK (risk_score BETWEEN 0 AND 100)
);

-- Aşağıdaki üç tablo simülasyonun cevap anahtarıdır. Gerçek bir şirkette
-- bu tablolar olmaz: örnek veri üretilirken kime, hangi aylarda, hangi
-- yollarla baskı uygulandığı buraya yazılır. Model bu etiketlerle eğitilir.

-- Senaryo: kime (employee_id), kim tarafından (perpetrator_id), hangi aylar
-- arasında ve hangi yollarla baskı uygulandı.
--   has_overload          fazla görev, dar süre, mesai dışı görev, ek mesai
--   has_exclusion         ekip toplantılarına çağırmama
--   has_leave_denial      izin başvurularını reddetme ve geciktirme
--   has_unfair_evaluation performans puanını düşürme
--   has_request_ignoring  talepleri görmeme, yanıtsız bırakma veya geciktirme
--   has_public_criticism  eleştiriyi ekip/departman önünde tekrarlama
CREATE TABLE simulation_scenarios (
  scenario_id           INT     NOT NULL AUTO_INCREMENT,
  employee_id           INT     NOT NULL,
  perpetrator_id        INT     NOT NULL,
  start_month           DATE    NOT NULL,
  end_month             DATE    NOT NULL,
  has_overload          BOOLEAN NOT NULL DEFAULT FALSE,
  has_exclusion         BOOLEAN NOT NULL DEFAULT FALSE,
  has_leave_denial      BOOLEAN NOT NULL DEFAULT FALSE,
  has_unfair_evaluation BOOLEAN NOT NULL DEFAULT FALSE,
  has_request_ignoring  BOOLEAN NOT NULL DEFAULT FALSE,
  has_public_criticism  BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (scenario_id),
  UNIQUE (employee_id),
  FOREIGN KEY (employee_id)    REFERENCES employees (employee_id),
  FOREIGN KEY (perpetrator_id) REFERENCES employees (employee_id)
);

-- Etiket: her çalışan ve her ay için tek satır.
-- is_mobbing = 1 ise çalışan o ay bir senaryonun içindedir.
CREATE TABLE simulation_labels (
  employee_id  INT     NOT NULL,
  period_month DATE    NOT NULL,
  is_mobbing   BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (employee_id, period_month),
  FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
);

-- Veri bölmesi: çalışanların yüzde 70'i eğitim (train), 15'i doğrulama
-- (validation), 15'i kullanım (test). Bölme çalışan bazındadır: aynı kişinin
-- ayları iki ayrı bölmeye düşmez.
CREATE TABLE dataset_splits (
  employee_id INT NOT NULL,
  split       ENUM('train','validation','test') NOT NULL,
  PRIMARY KEY (employee_id),
  FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
);
