# Mobbing Risk Analizi Sistemi: Veritabanı

Bu klasör projenin veritabanı kısmıdır: bir şirketi simüle eden MySQL veritabanının tabloları, içini dolduran örnek veri ve örnek sorgular. Veritabanı mobbingi kendisi tespit etmez; analiz için gereken veriyi düzenli, ilişkili ve sorgulanabilir biçimde saklar.

## Dosyalar

| Dosya | İçerik |
|---|---|
| `sql/01_schema.sql` | Veritabanı ve 16 tablo |
| `sql/02_seed.sql` | Örnek şirket verisi: 2025 yılı, 200 çalışan |
| `sql/03_queries.sql` | Örnek sorgular: temel listeler, göstergeler, cevap anahtarı, tutarlılık kontrolleri |
| `generator/generate_seed.py` | `02_seed.sql` dosyasını üreten Python betiği |

## Kurulum

Dosyalar sırayla çalıştırılır. MySQL Workbench'te her dosya File > Open SQL Script ile açılır ve şimşek düğmesiyle çalıştırılır. Komut satırından:

```
mysql -u root -p < sql/01_schema.sql
mysql -u root -p < sql/02_seed.sql
mysql -u root -p mobbing_risk < sql/03_queries.sql
```

Veritabanının adı `mobbing_risk`. Baştan kurmak için önce `DROP DATABASE mobbing_risk;` çalıştırılır. Dosyalar MySQL 8.0 ve MariaDB 10.4 (XAMPP) üzerinde denendi.

## Tablolar

**Organizasyon**

- `departments`: şirketteki departmanlar.
- `employees`: çalışanlar. `department_id` çalışanın departmanını, `manager_id` yöneticisini gösterir. Yönetici de bir çalışan olduğu için `manager_id` aynı tabloya bakar. Çalışan silinmez; işten ayrılınca `termination_date` doldurulur.

**Zaman**

- `attendance_logs`: günlük giriş ve çıkış saatleri. Bir çalışanın bir güne tek kaydı olur. Standart mesai 09:00 ile 18:00 arasıdır; bunu aşan süre ve hafta sonu çalışması ek mesaidir.
- `leave_requests`: izin başvuruları. `status` başvurunun bekleyen, onaylanan ya da reddedilen olduğunu, `decided_by` kararı veren yöneticiyi gösterir.

**İş**

- `tasks`: görevler. Kime verildi (`assigned_to`), kim verdi (`assigned_by`), ne zaman verildi, ne zaman istendi, ne zaman bitti.
- `meetings`: toplantılar. Dört türü vardır: ekip (`team`), departman (`department`), proje (`project`), şirket (`company`).
- `meeting_participants`: toplantıya davet edilenler. Bir çalışan birçok toplantıya, bir toplantı birçok çalışana bağlandığı için (çoka çok ilişki) ara tablodur. Satır varsa kişi davet edilmiştir; ekip toplantısına çağrılmayan ekip üyesinin satırı olmaz.

**Değerlendirme**

- `performance_reviews`: çeyreklik performans puanları (1.0 ile 5.0 arası).
- `complaints`: çalışanların bildirdiği olumsuz olaylar. `reporter_id` bildiren, `accused_id` hakkında bildirim yapılan kişidir.

**Anket**

- `surveys`: anketler.
- `survey_questions`: anket soruları. Sorular olumsuz ifadedir ve 1 ile 5 arasında puanlanır; puan yükseldikçe risk artar. `dimension` sorunun ölçtüğü boyuttur: iş yükü, dışlanma, haklar, adalet, saygı.
- `survey_answers`: çalışanın bir soruya verdiği puan.

**Analiz**

- `risk_assessments`: backend'in ürettiği risk puanı ve LLM raporu. Başlangıçta boştur.
- `simulation_scenarios`, `simulation_labels`, `dataset_splits`: simülasyonun cevap anahtarı. Aşağıda anlatılıyor.

## İlişkiler

```mermaid
erDiagram
    departments ||--o{ employees : "çalışır"
    employees ||--o{ employees : "yönetir"
    employees ||--o{ attendance_logs : "giriş çıkış yapar"
    employees ||--o{ leave_requests : "izin ister"
    employees ||--o{ tasks : "görev alır"
    employees ||--o{ meetings : "düzenler"
    meetings ||--o{ meeting_participants : "davet eder"
    employees ||--o{ meeting_participants : "davet edilir"
    employees ||--o{ performance_reviews : "değerlendirilir"
    employees ||--o{ complaints : "bildirir"
    surveys ||--o{ survey_questions : "içerir"
    survey_questions ||--o{ survey_answers : "yanıtlanır"
    employees ||--o{ survey_answers : "yanıtlar"
    employees ||--o{ risk_assessments : "analiz edilir"
    employees ||--o| simulation_scenarios : "senaryoya girer"
    employees ||--o{ simulation_labels : "etiketlenir"
    employees ||--|| dataset_splits : "bölmeye düşer"
```

Bazı tablolar `employees` tablosuna iki ayrı yabancı anahtarla bağlanır: `tasks` (alan ve veren), `leave_requests` (başvuran ve karar veren), `performance_reviews` (değerlendirilen ve değerlendiren), `complaints` (bildiren ve hakkında bildirilen).

## Örnek veri

Veri gerçek bir şirketten alınmadı, `generator/generate_seed.py` ile üretildi. 2025 yılı boyunca 9 departmanlı, 200 çalışanlı bir şirket simüle edilir.

| Tablo | Satır |
|---|---|
| departments | 9 |
| employees | 200 |
| attendance_logs | 46 680 |
| leave_requests | 803 |
| tasks | 21 253 |
| meetings | 2 126 |
| meeting_participants | 18 231 |
| performance_reviews | 768 |
| complaints | 22 |
| surveys | 2 |
| survey_questions | 20 |
| survey_answers | 3 360 |
| simulation_scenarios | 20 |
| simulation_labels | 2 344 |
| dataset_splits | 200 |

**Senaryolar.** 200 çalışanın 20'si bir senaryonun içindedir: yöneticisi belirli aylar arasında ona aşağıdaki dört yoldan biri ya da birkaçıyla baskı uygular. Dört yönetici birden çok kişiye baskı uygular.

| Baskı yolu | Veride nasıl görünür |
|---|---|
| Aşırı iş yükü (`has_overload`) | Departman ortalamasının üstünde görev, 24 saat içinde istenen işler, mesai dışında verilen görevler, uzun ek mesai, hafta sonu çalışması |
| Dışlama (`has_exclusion`) | Yöneticisinin ekip toplantılarına çağrılmama, proje toplantılarına daha az davet |
| İzin engelleme (`has_leave_denial`) | İzin başvurularının çoğunun reddedilmesi, kararın günlerce geciktirilmesi |
| Haksız değerlendirme (`has_unfair_evaluation`) | Performans puanının bir önceki çeyreğe göre belirgin düşmesi |

Senaryodaki çalışanların bir kısmı şikâyette bulunur, anketlerde daha yüksek puan verir, üçü yıl içinde işten ayrılır.

**Zararsız benzer durumlar.** Model yalnızca tek bir sayıya bakıp karar veremesin diye mobbing olmayan ama ona benzeyen durumlar da vardır: bütün ekibin yoğun çalıştığı dönemler (Yazılım Geliştirme Ekim ve Kasım, Satış Haziran, Finans Aralık), her zaman çok çalışan 10 kişi, puanı yıl boyu düşük olan 10 kişi, sıradan işlerde ara sıra verilen acil ve mesai dışı görevler, senaryoyla ilgisi olmayan şikâyetler.

**Cevap anahtarı.** Gerçek bir şirkette aşağıdaki üç tablo olmaz; simülasyonda doğru cevabı bildiğimiz için vardır.

- `simulation_scenarios`: kime, kim tarafından, hangi aylar arasında, hangi yollarla baskı uygulandı.
- `simulation_labels`: her çalışan ve her ay için tek satır. `is_mobbing = 1` ise çalışan o ay bir senaryonun içindedir. 2 344 çalışan-ayın 140'ı böyledir.
- `dataset_splits`: çalışanların yüzde 70'i eğitim (`train`), 15'i doğrulama (`validation`), 15'i kullanım (`test`) bölmesindedir. Bölme çalışan bazında yapıldı ki aynı kişinin ayları hem eğitimde hem sınamada yer almasın.

| Bölme | Çalışan | Çalışan-ay | Mobbing etiketli ay |
|---|---|---|---|
| train | 140 | 1 648 | 99 |
| validation | 30 | 353 | 22 |
| test | 30 | 343 | 19 |

## Göstergeler

Ön işleme ve backend için her mobbing belirtisinin hangi tablodan, hangi sorguyla çıktığı:

| Gösterge | Tablo | Sorgu (`03_queries.sql`) |
|---|---|---|
| Aylık ek mesai saati, hafta sonu çalışması | attendance_logs | B1 |
| İzin başvurusu ve onay oranı | leave_requests | B2, B3 |
| Görev yükünün departman ortalamasına oranı | tasks, employees | B4 |
| Mesai dışı, dar süreli ve geciken görevler | tasks | B5, B6 |
| Ekip toplantılarından dışlanma oranı | meetings, meeting_participants | B7 |
| Performans puanındaki düşüş | performance_reviews | B8 |
| Hakkındaki şikâyet sayısı | complaints | B9 |
| Anket boyut ortalamaları | survey_answers, survey_questions | B10 |

Aylık sorgularda ay, ayın ilk günü olarak yazılır (örnek: `2025-03-01`). `simulation_labels.period_month` ve `risk_assessments.period_month` aynı biçimdedir, böylece göstergeler etiketlerle doğrudan birleştirilir (örnek: sorgu C3).

## Veriyi yeniden üretmek

```
cd generator
python3 generate_seed.py --out ../sql/02_seed.sql
python3 generate_seed.py --employees 300 --seed 7 --out ../sql/02_seed.sql
```

Betik yalnız Python standart kütüphanesini kullanır. Aynı `--seed` değeri aynı veriyi üretir; `--employees` çalışan sayısını değiştirir.
