#!/usr/bin/env python3
"""Mobbing Risk Analizi veritabanı için örnek şirket verisi üretir (02_seed.sql).

Kullanım:
    python3 generate_seed.py --out ../sql/02_seed.sql
    python3 generate_seed.py --employees 300 --seed 7 --out ../sql/02_seed.sql

Yalnız Python standart kütüphanesini kullanır. Aynı --seed aynı veriyi üretir.

Simülasyonun mantığı:
  * 2025 yılı boyunca çalışan bir şirket kurulur (departman, ekip, yönetici).
  * Çalışanların yaklaşık yüzde 10'u bir "senaryo"ya girer: yöneticisi belirli
    aylar arasında ona altı yoldan biri ya da birkaçıyla baskı uygular:
      overload           fazla görev, dar süre, mesai dışı görev, ek mesai
      exclusion          ekip toplantılarına çağırmama
      leave_denial       izin başvurularını reddetme ve geciktirme
      unfair_evaluation  performans puanını düşürme
      request_ignoring   iş taleplerini görmeme, yanıtsız bırakma veya geciktirme
      public_criticism   eleştiriyi ekip ya da departman önünde tekrarlama
  * Modeli yanıltacak zararsız durumlar da eklenir: bütün ekibin yoğun çalıştığı
    dönemler, sürekli çok çalışanlar, puanı hep düşük olanlar.
  * Hangi çalışanın hangi ayda senaryo içinde olduğu simulation_* tablolarına
    yazılır; model bu etiketlerle eğitilir.
"""
import argparse
import calendar
import datetime as dt
import math
import random
import sys
from collections import defaultdict

YEAR = 2025
YEAR_START = dt.date(YEAR, 1, 1)
YEAR_END = dt.date(YEAR, 12, 31)
DATA_END = dt.datetime(YEAR, 12, 31, 23, 59, 59)
SHIFT_START, SHIFT_END = 9 * 60, 18 * 60   # standart mesai, gece yarısından dakika

# 2025 resmi tatillerinden hafta içine denk gelenler
HOLIDAYS = {dt.date(YEAR, m, d) for m, d in [
    (1, 1), (3, 31), (4, 1), (4, 23), (5, 1), (5, 19), (6, 6), (6, 9), (7, 15), (10, 29)]}

# (ad, çalışan payı, kişi başı aylık görev ortalaması); ilk satır sabit 3 kişidir
DEPARTMENTS = [
    ("Genel Müdürlük", None, 6),
    ("Yazılım Geliştirme", 0.24, 9),
    ("Müşteri Destek", 0.17, 12),
    ("Satış", 0.15, 10),
    ("Operasyon", 0.14, 10),
    ("Pazarlama", 0.09, 8),
    ("Finans", 0.08, 8),
    ("Ar-Ge", 0.07, 7),
    ("İnsan Kaynakları", 0.06, 8),
]
GM_DEPT = 1
GM_OFFICE_STAFF = 2

# Bütün ekibin yoğun çalıştığı dönemler (departman no, ay): mobbing değildir
CRUNCH = {(2, 10), (2, 11), (4, 6), (7, 12)}

# Kıdem seviyesi -> unvan
TITLES = {1: "Uzman Yardımcısı", 2: "Uzman", 3: "Kıdemli Uzman", 4: "Takım Lideri", 5: "Müdür", 6: "Genel Müdür"}
LEAD_LEVEL, MANAGER_LEVEL, CEO_LEVEL = 4, 5, 6

LEAVE_REJECT_BASE = {"annual": 0.08, "excuse": 0.10, "sick": 0.02, "unpaid": 0.25}
REJECT_NOTES = ["İş yoğunluğu nedeniyle uygun görülmedi.", "Aynı tarihte ekipte izinli personel var.",
                "Proje teslim dönemine denk geliyor.", "Daha sonra yeniden değerlendirilecek."]

COMPLAINT_TEXTS = {
    "overload": ["Ekipteki diğer kişilere göre çok daha fazla görev veriliyor ve süreler yetiştirilemeyecek kadar kısa tutuluyor.",
                 "Mesai bittikten sonra ve hafta sonu sürekli acil görev atanıyor, itiraz ettiğimde dikkate alınmıyor."],
    "exclusion": ["Ekibimin haftalık toplantılarına haftalardır çağrılmıyorum, alınan kararları sonradan başkalarından öğreniyorum.",
                  "İşimi doğrudan etkileyen bilgiler benimle paylaşılmıyor, toplantı davetlerinden çıkarıldım."],
    "rights": ["İzin taleplerim gerekçe gösterilmeden art arda reddediliyor, ekipteki diğer kişilerin talepleri onaylanıyor.",
               "İzin başvurularım günlerce cevapsız bırakılıyor, sonra reddediliyor."],
    "unfair_evaluation": ["Hedeflerimi tutturmama rağmen performans puanım açıklama yapılmadan düşürüldü.",
                          "Değerlendirme görüşmesinde yapmadığım hatalar bana mal edildi, itirazım kayda geçirilmedi."],
    "verbal": ["Yöneticim ekip önünde küçümseyici ifadeler kullanıyor ve yaptığım işi alaya alıyor.",
               "Toplantıda yüksek sesle azarlandım, bu durum ilk kez olmuyor."],
    "other": ["Ofis içi görev dağılımında yaşanan bir anlaşmazlığı bildirmek istiyorum.",
              "Çalışma arkadaşımla yaşadığım iletişim sorununun değerlendirilmesini rica ediyorum.",
              "Ortak alan kullanımıyla ilgili yaşanan tartışmayı bildiriyorum."],
}

SURVEYS = [("2025 Birinci Dönem Çalışma Ortamı Anketi", dt.date(YEAR, 6, 16), dt.date(YEAR, 6, 27)),
           ("2025 İkinci Dönem Çalışma Ortamı Anketi", dt.date(YEAR, 12, 8), dt.date(YEAR, 12, 19))]
SURVEY_DESCRIPTION = "Her ifade 1 (hiç katılmıyorum) ile 5 (tamamen katılıyorum) arasında puanlanır."
SURVEY_QUESTIONS = [
    ("workload", "Bana ekibimdeki diğer kişilere göre belirgin biçimde daha fazla iş veriliyor."),
    ("workload", "Bana yetiştirilmesi mümkün olmayan teslim süreleri veriliyor."),
    ("exclusion", "İşimle ilgili toplantılara çağrılmadığım oluyor."),
    ("exclusion", "İşimi etkileyen bilgiler benimle paylaşılmıyor."),
    ("rights", "İzin taleplerim geçerli bir gerekçe gösterilmeden reddediliyor."),
    ("rights", "Haklarımı kullanmak istediğimde zorluk çıkarılıyor."),
    ("fairness", "Performansım emeğimi yansıtmayan biçimde düşük değerlendiriliyor."),
    ("fairness", "Hatalarım başkalarının önünde abartılarak dile getiriliyor."),
    ("respect", "Yöneticim benimle küçümseyici bir dille konuşuyor."),
    ("respect", "İş yerinde kendimi yalnız bırakılmış hissediyorum."),
]
# Senaryo yolu -> (olasılık, ilgili anket boyutu, ilgili şikâyet kategorisi)
# Her yolun anket karşılığı olmak zorunda değildir; None ise yalnız operasyonel
# olaylardan ölçülür.
SCENARIO_FLAGS = {
    "overload": (0.60, "workload", "overload"),
    "exclusion": (0.55, "exclusion", "exclusion"),
    "leave_denial": (0.40, "rights", "rights"),
    "unfair_evaluation": (0.60, "fairness", "unfair_evaluation"),
    "request_ignoring": (0.45, None, "other"),
    "public_criticism": (0.40, "respect", "verbal"),
}
DIMENSION_FLAG = {dimension: flag for flag, (_, dimension, _) in SCENARIO_FLAGS.items() if dimension}

REVIEW_WINDOWS = {1: (dt.date(YEAR, 4, 7), dt.date(YEAR, 4, 18)), 2: (dt.date(YEAR, 7, 7), dt.date(YEAR, 7, 18)),
                  3: (dt.date(YEAR, 10, 6), dt.date(YEAR, 10, 17)), 4: (dt.date(YEAR, 12, 15), dt.date(YEAR, 12, 26))}
REVIEW_COMMENTS = [
    (4.5, ["Beklentilerin üzerinde performans gösterdi.", "Ekibine örnek olan bir dönem geçirdi."]),
    (3.5, ["Hedeflerini karşıladı.", "Görevlerini zamanında ve düzgün tamamladı."]),
    (2.5, ["Bazı hedeflerde geride kaldı, gelişim alanları konuşuldu.", "Dönem içinde dalgalı bir performans gösterdi."]),
    (0.0, ["Beklentilerin altında kaldı, yakından takip edilecek.", "Görevlerde gecikmeler yaşandı, uyarı yapıldı."]),
]

TASK_ACTIONS = {
    GM_DEPT: ["Yönetim sunumu hazırlığı", "Toplantı organizasyonu", "Rapor derleme"],
    2: ["Hata düzeltme", "Kod incelemesi", "Yeni özellik geliştirme", "Birim testi yazımı", "Sürüm hazırlığı", "Performans iyileştirme"],
    3: ["Müşteri talebi çözümü", "Şikâyet kaydı takibi", "Bilgi bankası güncelleme", "Geri arama", "Destek raporu"],
    4: ["Teklif hazırlama", "Müşteri ziyareti raporu", "Sözleşme takibi", "Fırsat güncelleme", "Satış sunumu"],
    5: ["Sevkiyat planı", "Stok sayımı", "Tedarikçi görüşmesi", "Süreç kontrolü", "Operasyon raporu"],
    6: ["Kampanya metni", "Sosyal medya planı", "Pazar araştırması", "Etkinlik hazırlığı", "Görsel revizyonu"],
    7: ["Fatura kontrolü", "Ödeme mutabakatı", "Bütçe raporu", "Masraf onayı", "Dönem kapanışı"],
    8: ["Prototip denemesi", "Literatür taraması", "Deney raporu", "Teknik fizibilite", "Model değerlendirme"],
    9: ["Aday görüşmesi", "İlan hazırlama", "Bordro kontrolü", "Eğitim planı", "Oryantasyon hazırlığı"],
}
TASK_SUBJECTS = ["Ödeme modülü", "Raporlama ekranı", "Mobil uygulama", "Kurumsal müşteriler", "Yeni ürün hattı",
                 "Bölge bayileri", "Yıllık plan", "İç denetim", "Müşteri portalı", "Bildirim servisi",
                 "Eğitim programı", "Tedarik zinciri", "Kullanıcı yönetimi", "Dönem sonu", "Pilot proje"]

FEMALE_NAMES = ["Ayşe", "Fatma", "Zeynep", "Elif", "Merve", "Büşra", "Esra", "Selin", "Derya", "Gamze", "Ceren",
                "Tuğba", "Özge", "Burcu", "Seda", "Hande", "İrem", "Gizem", "Melis", "Pınar", "Sibel", "Ebru",
                "Nazlı", "Aslı", "Damla", "Şeyma", "Cansu", "Yasemin", "Dilek", "Gül"]
MALE_NAMES = ["Mehmet", "Mustafa", "Ahmet", "Ali", "Hüseyin", "Emre", "Burak", "Murat", "Can", "Oğuz", "Serkan",
              "Kerem", "Onur", "Tolga", "Barış", "Cem", "Deniz", "Eren", "Gökhan", "Hakan", "İsmail", "Kaan",
              "Levent", "Okan", "Selim", "Tarık", "Umut", "Volkan", "Yusuf", "Çağrı"]
LAST_NAMES = ["Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Yıldız", "Yıldırım", "Öztürk", "Aydın", "Özdemir",
              "Arslan", "Doğan", "Kılıç", "Aslan", "Çetin", "Kara", "Koç", "Kurt", "Özkan", "Şimşek", "Polat",
              "Korkmaz", "Erdoğan", "Aksoy", "Güneş", "Bulut", "Taş", "Aktaş", "Güler", "Tekin", "Karaca",
              "Bozkurt", "Türk", "Uçar", "Avcı", "Sarı", "Coşkun", "Köse", "Yavuz", "Turan", "Kaplan", "Erdem",
              "Sezer", "Toprak", "Özer", "Işık", "Duman", "Çakır", "Tuncer", "Ateş"]
ASCII_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


# --------------------------------------------------------------------------
# Takvim yardımcıları
# --------------------------------------------------------------------------

def is_workday(day):
    return day.weekday() < 5 and day not in HOLIDAYS


def add_workdays(day, count):
    while count > 0:
        day += dt.timedelta(days=1)
        if is_workday(day):
            count -= 1
    return day


def days_between(first, last):
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def month_bounds(month):
    return dt.date(YEAR, month, 1), dt.date(YEAR, month, calendar.monthrange(YEAR, month)[1])


ALL_DAYS = days_between(YEAR_START, YEAR_END)
WORKDAYS = [d for d in ALL_DAYS if is_workday(d)]
WORKDAYS_BY_MONTH = {m: [d for d in WORKDAYS if d.month == m] for m in range(1, 13)}
DAYS_BY_MONTH = {m: [d for d in ALL_DAYS if d.month == m] for m in range(1, 13)}


def at(day, minutes):
    return dt.datetime.combine(day, dt.time(0, 0)) + dt.timedelta(minutes=int(minutes))


def clock(minutes):
    return f"{int(minutes) // 60:02d}:{int(minutes) % 60:02d}"


def clamp(value, low, high):
    return max(low, min(high, value))


# --------------------------------------------------------------------------
# Simülasyon
# --------------------------------------------------------------------------

class Simulation:
    def __init__(self, employee_count, seed):
        self.rng = random.Random(seed)
        self.employee_count = employee_count
        self.seed = seed
        self.employees = []                # sözlük listesi, sıra = employee_id sırası
        self.by_id = {}
        self.reports = defaultdict(list)   # yönetici no -> doğrudan bağlı çalışanlar
        self.scenarios = {}                # çalışan no -> senaryo sözlüğü
        self.approved_leave = defaultdict(set)
        self.tables = {}

    # ---- küçük yardımcılar ----

    def poisson(self, mean):
        if mean <= 0:
            return 0
        limit, count, product = math.exp(-mean), 0, self.rng.random()
        while product > limit:
            count += 1
            product *= self.rng.random()
        return count

    def weighted_sample(self, items, weights, count):
        items, weights, picked = list(items), list(weights), []
        while items and len(picked) < count:
            index = self.rng.choices(range(len(items)), weights)[0]
            picked.append(items.pop(index))
            weights.pop(index)
        return picked

    def employed(self, emp, day):
        return emp["start"] <= day <= emp["end"]

    def factor(self, emp_id, month, flag=None):
        """Çalışanın o aydaki senaryo şiddeti (0 = senaryo yok). İlk ay yarım şiddettedir."""
        scenario = self.scenarios.get(emp_id)
        if not scenario or not scenario["start"] <= month <= scenario["end"]:
            return 0.0
        if flag and not scenario[flag]:
            return 0.0
        return scenario["intensity"] * (0.55 if month == scenario["start"] else 1.0)

    def crunch(self, emp, month):
        return (emp["dept"], month) in CRUNCH

    # ---- 1. organizasyon ----

    def add_employee(self, dept, level, manager, hire_from, hire_to, age_from, age_to):
        rng = self.rng
        gender = rng.choice("FM")
        first = rng.choice(FEMALE_NAMES if gender == "F" else MALE_NAMES)
        last = rng.choice(LAST_NAMES)
        hire = rng.choice([d for d in days_between(hire_from, hire_to) if d.weekday() < 5])
        birth = dt.date(hire.year - rng.randint(age_from, age_to), rng.randint(1, 12), rng.randint(1, 28))
        base = f"{first}.{last}".translate(ASCII_MAP).lower()
        used = sum(1 for e in self.employees if e["email_base"] == base)
        emp = {
            "id": len(self.employees) + 1, "first": first, "last": last, "email_base": base,
            "email": f"{base}{used + 1 if used else ''}@example.com", "gender": gender, "birth": birth,
            "hire": hire, "term": None, "dept": dept, "level": level, "manager": manager,
            "checkin_offset": rng.uniform(-12, 6), "overtime_rate": rng.uniform(0.08, 0.30),
            "task_factor": rng.uniform(0.78, 1.25), "performance": clamp(rng.gauss(3.75, 0.42), 2.7, 4.8),
            "negativity": clamp(rng.gauss(1.9, 0.35), 1.2, 2.9), "workaholic": False,
        }
        self.employees.append(emp)
        self.by_id[emp["id"]] = emp
        if manager:
            self.reports[manager].append(emp["id"])
        return emp

    def build_organization(self):
        """Yönetici her zaman kendisine bağlı çalışandan önce oluşur (employee_id sırası)."""
        rng = self.rng
        ceo = self.add_employee(GM_DEPT, CEO_LEVEL, None, dt.date(2012, 1, 2), dt.date(2014, 12, 31), 40, 50)
        rest = self.employee_count - 1 - GM_OFFICE_STAFF
        sizes = {i + 1: round(share * rest) for i, (_, share, _) in enumerate(DEPARTMENTS) if share}
        sizes[2] += rest - sum(sizes.values())

        managers, leads, staff_plan = {}, defaultdict(list), []
        for dept in sizes:
            managers[dept] = self.add_employee(dept, MANAGER_LEVEL, ceo["id"], dt.date(2013, 1, 1), dt.date(2019, 12, 31), 34, 48)
        for dept, size in sizes.items():
            lead_count = 0 if size - 1 <= 8 else max(2, round((size - 1) / 9))
            for _ in range(lead_count):
                leads[dept].append(self.add_employee(dept, LEAD_LEVEL, managers[dept]["id"],
                                                     dt.date(2015, 1, 1), dt.date(2021, 12, 31), 30, 42))
            bosses = leads[dept] or [managers[dept]]
            staff_plan += [(dept, bosses[i % len(bosses)]["id"]) for i in range(size - 1 - lead_count)]
        staff_plan += [(GM_DEPT, ceo["id"])] * GM_OFFICE_STAFF

        staff_profile = {1: (dt.date(2021, 1, 1), dt.date(2024, 11, 29), 22, 27),
                         2: (dt.date(2018, 1, 1), dt.date(2024, 6, 28), 24, 33),
                         3: (dt.date(2016, 1, 1), dt.date(2021, 12, 31), 28, 40)}
        for dept, boss in staff_plan:
            level = rng.choices([1, 2, 3], [0.25, 0.50, 0.25])[0]
            self.add_employee(dept, level, boss, *staff_profile[level])

    def build_scenarios(self):
        """Senaryoya girecek çalışanları, işe girenleri ve ayrılanları seçer."""
        rng = self.rng
        staff = [e for e in self.employees if e["level"] < LEAD_LEVEL and e["dept"] != GM_DEPT]
        team = defaultdict(list)
        for emp in staff:
            team[emp["manager"]].append(emp)

        target_count = round(0.10 * self.employee_count)
        big_teams = [boss for boss, members in team.items() if len(members) >= 6]
        repeat_bosses = rng.sample(big_teams, min(len(big_teams), max(2, round(self.employee_count / 50))))
        targets = []
        for boss in repeat_bosses:   # birden çok kişiye baskı uygulayan yöneticiler
            targets += rng.sample(team[boss], rng.randint(3, 4))
        other_bosses = [boss for boss in team if boss not in repeat_bosses]
        for boss in rng.sample(other_bosses, min(len(other_bosses), max(0, target_count - len(targets)))):
            targets.append(rng.choice(team[boss]))

        for emp in targets:
            start = rng.randint(2, 8)
            end = 12 if rng.random() < 0.70 else min(11, start + rng.randint(3, 5))
            flags = {flag: rng.random() < chance for flag, (chance, _, _) in SCENARIO_FLAGS.items()}
            if not any(flags.values()):
                flags[rng.choice(list(SCENARIO_FLAGS))] = True
            self.scenarios[emp["id"]] = {"perpetrator": emp["manager"], "start": start, "end": end,
                                         "intensity": rng.uniform(0.75, 1.25), **flags}
            if flags["unfair_evaluation"]:
                emp["performance"] = max(emp["performance"], 3.5)

        # Baskı görenlerin bir kısmı istifa eder
        resign_pool = [e for e in targets if self.scenarios[e["id"]]["end"] == 12 and self.scenarios[e["id"]]["start"] <= 6]
        for emp in rng.sample(resign_pool, min(len(resign_pool), round(0.15 * len(targets)))):
            scenario = self.scenarios[emp["id"]]
            scenario["end"] = rng.randint(scenario["start"] + 5, 11)
            emp["term"] = rng.choice(WORKDAYS_BY_MONTH[scenario["end"]])

        others = [e for e in staff if e["id"] not in self.scenarios]
        rng.shuffle(others)
        new_hires = others[:round(0.04 * self.employee_count)]
        leavers = others[len(new_hires):len(new_hires) + round(0.035 * self.employee_count)]
        special = others[len(new_hires) + len(leavers):]
        for emp in new_hires:
            emp["hire"] = rng.choice([d for d in WORKDAYS if dt.date(YEAR, 2, 3) <= d <= dt.date(YEAR, 9, 30)])
        for emp in leavers:
            emp["term"] = rng.choice([d for d in WORKDAYS if dt.date(YEAR, 4, 1) <= d <= dt.date(YEAR, 11, 28)])
        # Zararsız ama modeli yanıltabilecek profiller
        twentieth = round(0.05 * self.employee_count)
        for emp in special[:twentieth]:
            emp["workaholic"], emp["overtime_rate"] = True, 0.75
        for emp in special[twentieth:2 * twentieth]:
            emp["performance"] = rng.uniform(2.0, 2.6)

        for emp in self.employees:
            emp["start"] = max(emp["hire"], YEAR_START)
            emp["end"] = min(emp["term"] or YEAR_END, YEAR_END)

    # ---- 2. izinler ----

    def build_leaves(self):
        rng, rows = self.rng, []
        for emp in self.employees:
            if not emp["manager"]:
                continue
            plan = [("annual", rng.choice([1, 2, 3, 5, 5, 10]), None) for _ in range(rng.choice([1, 2, 2, 3]))]
            plan += [("excuse", 1, None)] * self.poisson(1.2)
            plan += [("sick", rng.randint(1, 3), None)] * self.poisson(0.8)
            if rng.random() < 0.03:
                plan.append(("unpaid", rng.choice([5, 10]), None))
            scenario = self.scenarios.get(emp["id"])
            if scenario and scenario["leave_denial"]:   # reddedilince yeniden deneyen çalışan
                months = list(range(scenario["start"], scenario["end"] + 1))
                plan += [(rng.choice(["annual", "excuse"]), rng.choice([1, 1, 2, 3]), months) for _ in range(rng.randint(2, 3))]

            busy = set()
            for leave_type, length, months in plan:
                days = self.pick_leave_days(emp, leave_type, length, months, busy)
                if days:
                    busy.update(days)
                    rows.append(self.decide_leave(emp, leave_type, days))
        rows.sort(key=lambda row: row[4])
        self.tables["leave_requests"] = [(i + 1, *row) for i, row in enumerate(rows)]

    def pick_leave_days(self, emp, leave_type, length, months, busy):
        rng = self.rng
        month_pool = months or list(range(1, 13))
        weights = [3 if leave_type == "annual" and not months and 6 <= m <= 9 else 1 for m in month_pool]
        for _ in range(8):
            month = rng.choices(month_pool, weights)[0]
            candidates = [d for d in WORKDAYS_BY_MONTH[month] if emp["start"] < d <= emp["end"]]
            if not candidates:
                continue
            index = WORKDAYS.index(rng.choice(candidates))
            days = [d for d in WORKDAYS[index:index + length] if d <= emp["end"]]
            if not busy.intersection(days):
                return days
        return None

    def decide_leave(self, emp, leave_type, days):
        rng, first = self.rng, days[0]
        if leave_type == "sick":
            requested = at(first, rng.randint(7 * 60 + 30, 9 * 60 + 15))
        else:
            day = first - dt.timedelta(days=rng.randint(3, 30))
            while day.weekday() >= 5:
                day -= dt.timedelta(days=1)
            requested = at(max(day, emp["hire"]), rng.randint(9 * 60, 17 * 60 + 30))

        denial = self.factor(emp["id"], first.month, "leave_denial")
        if denial:
            reject_chance = min(0.92, 0.72 * denial)
            decided = requested + dt.timedelta(days=rng.uniform(3, 9))
        else:
            reject_chance = LEAVE_REJECT_BASE[leave_type] + (0.25 if self.crunch(emp, first.month) else 0)
            decided = requested + (dt.timedelta(hours=rng.uniform(1, 6)) if leave_type == "sick"
                                   else dt.timedelta(days=rng.uniform(0.1, 3.0)))
        decided = decided.replace(second=0, microsecond=0)

        if decided > DATA_END:
            return (emp["id"], leave_type, first, days[-1], requested, "pending", None, None, None)
        if rng.random() < reject_chance:
            return (emp["id"], leave_type, first, days[-1], requested, "rejected", emp["manager"], decided, rng.choice(REJECT_NOTES))
        self.approved_leave[emp["id"]].update(days_between(first, days[-1]))   # aradaki hafta sonları dahil
        return (emp["id"], leave_type, first, days[-1], requested, "approved", emp["manager"], decided, None)

    # ---- 3. giriş çıkış ----

    def build_attendance(self):
        rng, rows = self.rng, []
        for emp in self.employees:
            for day in days_between(emp["start"], emp["end"]):
                overload = self.factor(emp["id"], day.month, "overload")
                crunch = self.crunch(emp, day.month)
                if day in self.approved_leave[emp["id"]]:
                    continue
                if is_workday(day):
                    if rng.random() < 0.008:
                        continue
                    check_in = SHIFT_START + clamp(rng.gauss(emp["checkin_offset"], 9), -45, 90)
                    extra = min(180, rng.expovariate(1 / 45)) if rng.random() < emp["overtime_rate"] else rng.gauss(4, 8)
                    if crunch and rng.random() < 0.60:
                        extra += max(0, rng.gauss(75, 30))
                    if overload and rng.random() < 0.70:
                        extra += max(0, rng.gauss(115, 40)) * overload
                    check_out = clamp(SHIFT_END + extra, check_in + 60, 23 * 60 + 30)
                elif day not in HOLIDAYS:
                    chance = 0.22 * overload + (0.10 if crunch else 0) + (0.05 if emp["workaholic"] else 0)
                    if rng.random() >= chance * (1.0 if day.weekday() == 5 else 0.4):
                        continue
                    check_in = clamp(rng.gauss(10 * 60, 50), 8 * 60, 13 * 60)
                    check_out = check_in + rng.uniform(180, 360)
                else:
                    continue
                rows.append((emp["id"], day, clock(check_in), clock(check_out)))
        rows.sort(key=lambda row: (row[1], row[0]))
        self.tables["attendance_logs"] = rows

    # ---- 4. çalışan talepleri ----

    def build_requests(self):
        """İş talepleri; görülme, ilk yanıt ve çözüm zamanları birbirinden ayrıdır."""
        rng, rows = self.rng, []
        staff = [e for e in self.employees if e["manager"]]
        request_types = ["information", "approval", "resource", "schedule", "other"]

        for emp in staff:
            for month in range(1, 13):
                days = [d for d in WORKDAYS_BY_MONTH[month] if self.employed(emp, d)]
                if not days:
                    continue
                count = self.poisson(1.7 * len(days) / len(WORKDAYS_BY_MONTH[month]))
                ignoring = self.factor(emp["id"], month, "request_ignoring")
                if ignoring:
                    count += self.poisson(1.2 * ignoring)

                for _ in range(count):
                    day = rng.choice(days)
                    created = at(day, rng.randint(8 * 60 + 30, 17 * 60 + 30))
                    colleagues = [e for e in self.employees
                                  if e["dept"] == emp["dept"] and e["id"] != emp["id"]
                                  and self.employed(e, day)]
                    if ignoring and rng.random() < 0.72:
                        recipient = self.scenarios[emp["id"]]["perpetrator"]
                    elif rng.random() < 0.72:
                        recipient = emp["manager"]
                    elif colleagues:
                        recipient = rng.choice(colleagues)["id"]
                    else:
                        recipient = emp["manager"]

                    targeted = bool(ignoring and recipient == self.scenarios[emp["id"]]["perpetrator"])
                    busy = self.crunch(emp, month)
                    priority = rng.choices(["low", "medium", "high"], [0.18, 0.65, 0.17])[0]
                    request_type = rng.choices(request_types, [0.34, 0.24, 0.15, 0.18, 0.09])[0]

                    if targeted and rng.random() < 0.24:
                        seen = response = resolved = outcome = None
                    else:
                        seen_hours = rng.uniform(18, 96) * ignoring if targeted else rng.uniform(0.05, 10 + 24 * busy)
                        seen = (created + dt.timedelta(hours=seen_hours)).replace(second=0, microsecond=0)
                        no_response = rng.random() < (0.52 if targeted else 0.12 if busy else 0.055)
                        if no_response or seen > DATA_END:
                            response = resolved = outcome = None
                            if seen > DATA_END:
                                seen = None
                        else:
                            response_hours = rng.uniform(36, 168) * ignoring if targeted else rng.uniform(0.1, 18 + 36 * busy)
                            response = (seen + dt.timedelta(hours=response_hours)).replace(second=0, microsecond=0)
                            if response > DATA_END:
                                response = None
                                resolved = outcome = None
                            elif rng.random() < (0.60 if targeted else 0.88):
                                resolved = (response + dt.timedelta(hours=rng.uniform(0.2, 72))).replace(second=0, microsecond=0)
                                if resolved > DATA_END:
                                    resolved = outcome = None
                                else:
                                    outcome = rng.choices(["approved", "rejected", "partial", "no_action"],
                                                          [0.56, 0.17, 0.20, 0.07] if not targeted
                                                          else [0.22, 0.24, 0.20, 0.34])[0]
                            else:
                                resolved = outcome = None
                    rows.append((emp["id"], recipient, request_type, priority, created,
                                 seen, response, resolved, outcome))

        rows.sort(key=lambda row: row[4])
        self.tables["employee_requests"] = [(i + 1, *row) for i, row in enumerate(rows)]

    # ---- 5. görevler ----

    def build_tasks(self):
        rng, rows = self.rng, []
        for emp in self.employees:
            if not emp["manager"]:
                continue
            rate = DEPARTMENTS[emp["dept"] - 1][2] * emp["task_factor"] * (0.45 if emp["level"] >= LEAD_LEVEL else 1.0)
            scenario = self.scenarios.get(emp["id"])
            for month in range(1, 13):
                workdays = [d for d in WORKDAYS_BY_MONTH[month] if self.employed(emp, d)]
                if not workdays:
                    continue
                share = len(workdays) / len(WORKDAYS_BY_MONTH[month])
                overload, crunch = self.factor(emp["id"], month, "overload"), self.crunch(emp, month)
                normal = self.poisson(rate * share * (1.5 if crunch else 1.0))
                rows += [self.normal_task(emp, workdays, overload, crunch) for _ in range(normal)]
                if overload:
                    all_days = [d for d in DAYS_BY_MONTH[month] if self.employed(emp, d)]
                    extra = self.poisson(rate * share * rng.uniform(0.9, 1.5) * overload)
                    rows += [self.pressure_task(emp, scenario, workdays, all_days) for _ in range(extra)]
        rows.sort(key=lambda row: row[3])
        tasks = [(i + 1, *row) for i, row in enumerate(rows)]
        self.tables["tasks"] = tasks
        self.build_task_changes(tasks)

    def task_row(self, emp, assigner, assigned, due, completed, priority, hours, effort_factor=1.0):
        if completed and completed > DATA_END:
            completed = None
        if completed:
            status = "done"
        elif due <= DATA_END and assigned.month < 12:
            status = "cancelled"
        else:
            status = self.rng.choice(["open", "in_progress"])
        actual_hours = None
        if completed:
            late_factor = 1.18 if completed > due else 1.0
            actual_hours = round(clamp(self.rng.gauss(hours * effort_factor * late_factor, max(0.6, hours * 0.18)), 0.5, 99.0), 1)
        title = f"{self.rng.choice(TASK_ACTIONS[emp['dept']])}: {self.rng.choice(TASK_SUBJECTS)}"
        return (title, emp["id"], assigner, assigned, due, completed, priority, hours, actual_hours, status)

    def finish_within(self, assigned, due):
        """Dar süreli görevin süresi içinde bitiş anı."""
        return assigned + dt.timedelta(minutes=int(self.rng.uniform(0.5, 0.98) * (due - assigned).total_seconds() / 60))

    def normal_task(self, emp, workdays, overload, crunch):
        rng = self.rng
        day = rng.choice(workdays)
        # Sıradan işlerde de arada mesai dışı ve acil görev olur; yoğun dönemde daha sık
        after_hours = rng.random() < (0.08 if crunch else 0.02)
        urgent = rng.random() < (0.10 if crunch else 0.03)
        assigned = at(day, rng.randint(19 * 60, 21 * 60 + 30) if after_hours else rng.randint(9 * 60, 17 * 60))
        hours = rng.choice([2, 3, 4, 4, 6, 8, 8, 12, 16])
        if urgent:
            due_day = None
            due = assigned + dt.timedelta(minutes=rng.randint(4 * 60, 24 * 60))
        else:
            due_day = add_workdays(day, max(1, round(hours / 4)) + rng.randint(1, 6))
            due = at(due_day, rng.choice([12, 17, 18]) * 60)

        boss = self.by_id[emp["manager"]]
        roll = rng.random()
        if roll < 0.12 and boss["manager"]:
            assigner = boss["manager"]
        elif roll < 0.20 and emp["level"] < LEAD_LEVEL:   # departmandaki başka bir yönetici
            assigner = rng.choice([e["id"] for e in self.employees
                                   if e["dept"] == emp["dept"] and e["level"] >= LEAD_LEVEL])
        else:
            assigner = boss["id"]

        on_time, late = (0.70, 0.22) if overload else (0.86, 0.10)
        roll, completed = rng.random(), None
        if roll < on_time and urgent:
            completed = self.finish_within(assigned, due)
        elif roll < on_time:
            finish_day = rng.choice([d for d in days_between(day, due_day) if is_workday(d)])
            completed = at(finish_day, rng.randint(9 * 60, 17 * 60 + 59))
            if completed <= assigned:
                completed = assigned + dt.timedelta(minutes=rng.randint(45, 240))
            if completed > due:
                completed = due - dt.timedelta(minutes=rng.randint(5, 90))
        elif roll < on_time + late:
            completed = due + dt.timedelta(minutes=rng.randint(120, 72 * 60))
        priority = "urgent" if urgent else rng.choices(["low", "medium", "high"], [0.22, 0.56, 0.22])[0]
        return self.task_row(emp, assigner, assigned, due, completed, priority, hours,
                             1.12 if overload or crunch else 1.0)

    def pressure_task(self, emp, scenario, workdays, all_days):
        """Senaryodaki yöneticinin verdiği görev: dar süreli, çoğu acil, sık sık mesai dışı."""
        rng = self.rng
        if rng.random() < 0.42:
            day = rng.choice(all_days)
            assigned = at(day, rng.randint(19 * 60, 22 * 60 + 30) if is_workday(day) else rng.randint(10 * 60, 19 * 60 + 59))
        else:
            assigned = at(rng.choice(workdays), rng.randint(9 * 60, 17 * 60))
        due = assigned + dt.timedelta(minutes=rng.randint(6 * 60, 30 * 60))
        roll, completed = rng.random(), None
        if roll < 0.50:
            completed = self.finish_within(assigned, due)
        elif roll < 0.88:
            completed = due + dt.timedelta(minutes=rng.randint(4 * 60, 96 * 60))
        priority = rng.choices(["urgent", "high", "medium"], [0.5, 0.4, 0.1])[0]
        return self.task_row(emp, scenario["perpetrator"], assigned, due, completed, priority,
                             rng.choice([6, 8, 12, 16, 20]), 1.30)

    def build_task_changes(self, tasks):
        """Görev geçmişine hem sıradan revizyonlar hem hedefli son tarih baskısı ekler."""
        rng, rows = self.rng, []
        for task in tasks:
            task_id, _, assigned_to, assigned_by, assigned_at, due_at = task[:6]
            scenario = self.scenarios.get(assigned_to)
            overload = self.factor(assigned_to, assigned_at.month, "overload")
            targeted = bool(overload and scenario and assigned_by == scenario["perpetrator"])
            if rng.random() >= (0.24 if targeted else 0.065):
                continue

            change_type = rng.choices(
                ["deadline_shortened", "deadline_extended", "priority_increased", "reassigned"],
                [0.58, 0.06, 0.31, 0.05] if targeted else [0.20, 0.43, 0.27, 0.10]
            )[0]
            span_minutes = max(30, int((due_at - assigned_at).total_seconds() / 60))
            changed_at = assigned_at + dt.timedelta(minutes=rng.randint(15, max(15, int(span_minutes * 0.65))))
            if change_type == "deadline_shortened":
                old_due = due_at + dt.timedelta(hours=rng.randint(12, 96))
                new_due = due_at
            elif change_type == "deadline_extended":
                old_due = max(assigned_at + dt.timedelta(minutes=30),
                              due_at - dt.timedelta(hours=rng.randint(6, 48)))
                new_due = due_at
            else:
                old_due = new_due = None
            rows.append((task_id, assigned_by, change_type, old_due, new_due, changed_at))
        rows.sort(key=lambda row: row[5])
        self.tables["task_changes"] = [(i + 1, *row) for i, row in enumerate(rows)]

    # ---- 6. toplantılar ----

    def build_meetings(self):
        rng, meetings = self.rng, []   # son öğe: {çalışan: davet ayrıntıları}
        ceo = self.employees[0]

        def add(day, minutes, kind, organizer, duration, title, invited, attend_rate):
            starts = at(day, minutes)
            organizer_invited = starts - dt.timedelta(days=7)
            people = {organizer: (organizer_invited, organizer_invited, None, "accepted", 1)}
            for emp_id in invited:
                if emp_id != organizer and self.employed(self.by_id[emp_id], day):
                    exclusion = self.factor(emp_id, day.month, "exclusion")
                    if exclusion and rng.random() < 0.45:
                        invited_at = starts - dt.timedelta(minutes=rng.randint(20, 6 * 60))
                    else:
                        invited_at = starts - dt.timedelta(hours=rng.uniform(18, 9 * 24))
                    invited_at = invited_at.replace(second=0, microsecond=0)
                    removed_chance = 0.18 * exclusion + 0.015
                    if rng.random() < removed_chance:
                        removed_at = invited_at + (starts - invited_at) * rng.uniform(0.2, 0.9)
                        people[emp_id] = (invited_at, None, removed_at.replace(second=0, microsecond=0), "removed", 0)
                        continue
                    if rng.random() < 0.08:
                        responded_at, status, attended = None, "invited", 0
                    else:
                        responded_at = invited_at + (starts - invited_at) * rng.uniform(0.05, 0.8)
                        if day in self.approved_leave[emp_id] or rng.random() > 0.93:
                            status, attended = "declined", 0
                        else:
                            status = "accepted"
                            attended = int(rng.random() < attend_rate)
                        responded_at = responded_at.replace(second=0, microsecond=0)
                    people[emp_id] = (invited_at, responded_at, None, status, attended)
            meetings.append((starts, kind, organizer, duration, title, people))

        # Haftalık ekip toplantıları: yönetici kendi ekibini çağırır
        for boss_id, members in self.reports.items():
            weekday, minutes, duration = rng.randint(0, 3), rng.choice([10, 11, 14, 15]) * 60 + rng.choice([0, 30]), rng.choice([30, 45, 60])
            for day in WORKDAYS:
                if day.weekday() != weekday:
                    continue
                invited = []
                for emp_id in members:
                    excluded = self.factor(emp_id, day.month, "exclusion")
                    chance = clamp(0.62 - 0.42 * excluded, 0.10, 0.75) if excluded else 0.985
                    if rng.random() < chance:
                        invited.append(emp_id)
                add(day, minutes, "team", boss_id, duration, "Haftalık Ekip Toplantısı", invited, 0.90)

        dept_members = defaultdict(list)
        for emp in self.employees:
            dept_members[emp["dept"]].append(emp)
        for month in range(1, 13):
            workdays = WORKDAYS_BY_MONTH[month]
            first_wednesday = next(d for d in workdays if d.weekday() == 2)
            last_friday = [d for d in workdays if d.weekday() == 4][-1]
            add(last_friday, 16 * 60, "company", ceo["id"], 60, "Aylık Şirket Toplantısı", [e["id"] for e in self.employees], 0.80)
            for dept, members in dept_members.items():
                head = next(e for e in members if e["level"] >= MANAGER_LEVEL)
                add(first_wednesday, 15 * 60, "department", head["id"], 60,
                    f"Aylık Departman Toplantısı: {DEPARTMENTS[dept - 1][0]}", [e["id"] for e in members], 0.85)
                if dept == GM_DEPT:
                    continue
                # Proje toplantıları: konuya göre seçilen kişiler; dışlanan çalışan daha az seçilir
                for _ in range(max(2, round(len(members) / 6))):
                    day = rng.choice(workdays)
                    present = [e for e in members if self.employed(e, day)]
                    organizer = rng.choice([e for e in present if e["level"] >= 3] or present)
                    weights = [0.25 if self.factor(e["id"], month, "exclusion") else 1.0 for e in present]
                    invited = [e["id"] for e in self.weighted_sample(present, weights, rng.randint(3, 8))]
                    if rng.random() < 0.25:
                        invited += [e["id"] for e in rng.sample(self.employees, rng.randint(1, 2))]
                    add(day, rng.randint(10, 16) * 60, "project", organizer["id"], rng.choice([30, 45, 60, 90]),
                        f"Proje Toplantısı: {rng.choice(TASK_SUBJECTS)}", invited, 0.90)

        meetings.sort(key=lambda m: m[0])
        self.tables["meetings"] = [(i + 1, m[4], m[1], m[2], m[0], m[3]) for i, m in enumerate(meetings)]
        self.tables["meeting_participants"] = [(i + 1, emp_id, *details)
                                               for i, m in enumerate(meetings) for emp_id, details in m[5].items()]

    # ---- 7. geri bildirim ----

    def build_feedback(self):
        rng, rows = self.rng, []
        for emp in self.employees:
            if not emp["manager"]:
                continue
            for month in range(1, 13):
                days = [d for d in WORKDAYS_BY_MONTH[month] if self.employed(emp, d)]
                if not days:
                    continue
                public_criticism = self.factor(emp["id"], month, "public_criticism")
                count = self.poisson(0.9 + 0.8 * public_criticism)
                for _ in range(count):
                    created = at(rng.choice(days), rng.randint(9 * 60, 17 * 60 + 30))
                    if public_criticism and rng.random() < 0.70:
                        feedback_type = rng.choices(["criticism", "warning", "correction"], [0.62, 0.16, 0.22])[0]
                        visibility = rng.choices(["team", "department", "private"], [0.64, 0.20, 0.16])[0]
                    else:
                        feedback_type = rng.choices(["praise", "correction", "warning", "criticism"],
                                                    [0.51, 0.31, 0.08, 0.10])[0]
                        if feedback_type == "praise":
                            visibility = rng.choices(["private", "team", "department"], [0.38, 0.53, 0.09])[0]
                        else:
                            visibility = rng.choices(["private", "team", "department"], [0.84, 0.14, 0.02])[0]
                    rows.append((emp["id"], emp["manager"], feedback_type, visibility, created))
        rows.sort(key=lambda row: row[4])
        self.tables["feedback_events"] = [(i + 1, *row) for i, row in enumerate(rows)]

    # ---- 8. performans ----

    def build_reviews(self):
        rng, rows = self.rng, []
        for quarter, (window_start, window_end) in REVIEW_WINDOWS.items():
            months = range(3 * quarter - 2, 3 * quarter + 1)
            quarter_end = month_bounds(3 * quarter)[1]
            review_days = [d for d in WORKDAYS if window_start <= d <= window_end]
            for emp in self.employees:
                reviewed = rng.choice(review_days)
                if not emp["manager"] or not self.employed(emp, reviewed) or emp["hire"] > quarter_end - dt.timedelta(days=45):
                    continue
                score = emp["performance"] + rng.gauss(0, 0.28)
                unfair_months = sum(1 for m in months if self.factor(emp["id"], m, "unfair_evaluation"))
                if unfair_months:
                    score -= rng.uniform(1.1, 1.7) * self.scenarios[emp["id"]]["intensity"] * (0.6 if unfair_months == 1 else 1.0)
                elif any(self.factor(emp["id"], m, "overload") for m in months):
                    score -= rng.uniform(0.1, 0.5)
                score = clamp(round(score * 2) / 2, 1.0, 5.0)
                comment = rng.choice(next(texts for limit, texts in REVIEW_COMMENTS if score >= limit))
                rows.append((emp["id"], emp["manager"], YEAR, quarter, score, comment, reviewed))
        self.tables["performance_reviews"] = [(i + 1, *row) for i, row in enumerate(rows)]

    # ---- 7. şikâyetler ----

    def build_complaints(self):
        rng, rows = self.rng, []

        def add(reporter, accused, category, month):
            days = [d for d in WORKDAYS_BY_MONTH[month] if self.employed(reporter, d)]
            if not days:
                return
            reported = at(rng.choice(days), rng.randint(9 * 60, 17 * 60 + 59))
            status = rng.choices(["open", "investigating", "resolved", "dismissed"], [0.30, 0.35, 0.20, 0.15])[0]
            rows.append((reporter["id"], accused, category, reported.date() - dt.timedelta(days=rng.randint(0, 10)),
                         reported, rng.choice(COMPLAINT_TEXTS[category]), status, int(rng.random() < 0.35)))

        victims_of = defaultdict(list)
        for emp_id, scenario in self.scenarios.items():
            victims_of[scenario["perpetrator"]].append(emp_id)
            if scenario["start"] + 2 > scenario["end"]:
                continue
            categories = [category for flag, (_, _, category) in SCENARIO_FLAGS.items() if scenario[flag]] + ["verbal"]
            for chance in (0.45, 0.15):   # kimi hiç bildirmez, kimi iki kez bildirir
                if rng.random() < chance:
                    add(self.by_id[emp_id], scenario["perpetrator"], rng.choice(categories),
                        rng.randint(scenario["start"] + 2, scenario["end"]))
        for boss, victims in victims_of.items():   # olaya tanık olan ekip arkadaşı
            witnesses = [e for e in self.reports[boss] if e not in victims]
            if len(victims) >= 3 and witnesses:
                add(self.by_id[rng.choice(witnesses)], boss, "verbal", rng.randint(6, 12))
        staff = [e for e in self.employees if e["level"] < LEAD_LEVEL and e["id"] not in self.scenarios]
        for reporter in rng.sample(staff, round(0.05 * self.employee_count)):   # senaryo dışı sıradan şikâyetler
            colleagues = [e["id"] for e in self.employees if e["dept"] == reporter["dept"] and e["id"] != reporter["id"]]
            accused = rng.choice(colleagues) if colleagues and rng.random() < 0.8 else None
            add(reporter, accused, rng.choices(["other", "verbal", "overload"], [0.6, 0.2, 0.2])[0], rng.randint(1, 12))

        rows.sort(key=lambda row: row[4])
        self.tables["complaints"] = [(i + 1, *row) for i, row in enumerate(rows)]

    # ---- 8. anketler ----

    def build_surveys(self):
        rng = self.rng
        surveys, questions, answers = [], [], []
        for survey_id, (title, opens, closes) in enumerate(SURVEYS, start=1):
            surveys.append((survey_id, title, SURVEY_DESCRIPTION, opens, closes))
            survey_questions = []
            for order, (dimension, text) in enumerate(SURVEY_QUESTIONS, start=1):
                questions.append((len(questions) + 1, survey_id, order, text, dimension))
                survey_questions.append((len(questions), dimension))
            month = closes.month
            for emp in self.employees:
                scenario = self.scenarios.get(emp["id"])
                active = self.factor(emp["id"], month)
                if emp["hire"] > opens or not self.employed(emp, closes) or rng.random() > (0.78 if active else 0.86):
                    continue
                answered = at(rng.choice([d for d in WORKDAYS if opens <= d <= closes]), rng.randint(9 * 60, 17 * 60 + 59))
                busy_team = self.crunch(emp, month) or self.crunch(emp, month - 1)
                for question_id, dimension in survey_questions:
                    mean = emp["negativity"]
                    if active and dimension == "respect":
                        mean = min(4.6, 3.3 + 0.5 * scenario["intensity"])
                    elif active and scenario[DIMENSION_FLAG[dimension]]:
                        mean = min(4.7, 3.6 + 0.6 * scenario["intensity"])
                    elif active:
                        mean += 0.8
                    elif scenario and month > scenario["end"]:
                        mean += 0.6
                    if busy_team and dimension == "workload":
                        mean += 1.1
                    answers.append((question_id, emp["id"], int(clamp(round(rng.gauss(mean, 0.7)), 1, 5)), answered))
        self.tables.update(surveys=surveys, survey_questions=questions, survey_answers=answers)

    # ---- 9. etiketler ve veri bölmesi ----

    def build_labels(self):
        rng = self.rng
        labels = [(emp["id"], dt.date(YEAR, month, 1), int(self.factor(emp["id"], month) > 0))
                  for emp in self.employees for month in range(1, 13)
                  if emp["start"] <= month_bounds(month)[1] and emp["end"] >= month_bounds(month)[0]]
        splits = []
        for group in ([e["id"] for e in self.employees if e["id"] in self.scenarios],
                      [e["id"] for e in self.employees if e["id"] not in self.scenarios]):
            rng.shuffle(group)   # senaryodakiler ve diğerleri ayrı ayrı bölünür ki her bölmede örnek olsun
            train, validation = round(0.70 * len(group)), round(0.15 * len(group))
            splits += [(emp_id, "train" if i < train else "validation" if i < train + validation else "test")
                       for i, emp_id in enumerate(group)]
        scenarios = [(i + 1, emp_id, s["perpetrator"], dt.date(YEAR, s["start"], 1), dt.date(YEAR, s["end"], 1),
                      *(int(s[flag]) for flag in SCENARIO_FLAGS))
                     for i, (emp_id, s) in enumerate(sorted(self.scenarios.items()))]
        self.tables.update(simulation_scenarios=scenarios, simulation_labels=labels, dataset_splits=sorted(splits))

    def run(self):
        self.build_organization()
        self.build_scenarios()
        self.build_leaves()
        self.build_attendance()
        self.build_requests()
        self.build_tasks()
        self.build_meetings()
        self.build_feedback()
        self.build_reviews()
        self.build_complaints()
        self.build_surveys()
        self.build_labels()
        self.tables["departments"] = [(i + 1, name) for i, (name, _, _) in enumerate(DEPARTMENTS)]
        self.tables["employees"] = [
            (e["id"], e["first"], e["last"], e["email"], e["gender"], e["birth"], e["hire"], e["term"],
             TITLES[e["level"]], e["dept"], e["manager"]) for e in self.employees]
        return self


# --------------------------------------------------------------------------
# SQL çıktısı
# --------------------------------------------------------------------------

# Yazım sırası yabancı anahtar sırasıdır: önce bakılan tablo, sonra bakan tablo.
TABLE_COLUMNS = [
    ("departments", "department_id, name"),
    ("employees", "employee_id, first_name, last_name, email, gender, birth_date, hire_date, termination_date, "
                  "title, department_id, manager_id"),
    ("leave_requests", "leave_request_id, employee_id, leave_type, start_date, end_date, requested_at, status, "
                       "decided_by, decided_at, decision_note"),
    ("attendance_logs", "employee_id, work_date, check_in, check_out"),
    ("employee_requests", "request_id, requester_id, recipient_id, request_type, priority, created_at, seen_at, "
                          "first_response_at, resolved_at, outcome"),
    ("tasks", "task_id, title, assigned_to, assigned_by, assigned_at, due_at, completed_at, priority, "
              "estimated_hours, actual_hours, status"),
    ("task_changes", "task_change_id, task_id, changed_by, change_type, old_due_at, new_due_at, changed_at"),
    ("meetings", "meeting_id, title, meeting_type, organizer_id, starts_at, duration_minutes"),
    ("meeting_participants", "meeting_id, employee_id, invited_at, responded_at, removed_at, invitation_status, attended"),
    ("feedback_events", "feedback_id, employee_id, given_by, feedback_type, visibility, created_at"),
    ("performance_reviews", "review_id, employee_id, reviewer_id, period_year, period_quarter, score, comment, reviewed_at"),
    ("complaints", "complaint_id, reporter_id, accused_id, category, occurred_on, reported_at, description, status, is_anonymous"),
    ("surveys", "survey_id, title, description, opens_on, closes_on"),
    ("survey_questions", "question_id, survey_id, question_order, question_text, dimension"),
    ("survey_answers", "question_id, employee_id, score, answered_at"),
    ("simulation_scenarios", "scenario_id, employee_id, perpetrator_id, start_month, end_month, has_overload, "
                             "has_exclusion, has_leave_denial, has_unfair_evaluation, has_request_ignoring, "
                             "has_public_criticism"),
    ("simulation_labels", "employee_id, period_month, is_mobbing"),
    ("dataset_splits", "employee_id, split"),
]
BATCH_SIZE = 500


def sql_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dt.datetime):
        return f"'{value:%Y-%m-%d %H:%M:%S}'"
    if isinstance(value, dt.date):
        return f"'{value:%Y-%m-%d}'"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def write_sql(sim, out):
    out.write("-- Mobbing Risk Analizi Sistemi: örnek şirket verisi\n")
    out.write(f"-- generator/generate_seed.py ile üretildi (çalışan: {sim.employee_count}, seed: {sim.seed}, yıl: {YEAR}).\n")
    out.write("-- Elle düzenlenmez; değişiklik üreteçte yapılır ve dosya yeniden üretilir.\n\n")
    out.write("USE mobbing_risk;\nSET NAMES utf8mb4;\n\n")
    for table, columns in TABLE_COLUMNS:
        rows = sim.tables[table]
        out.write(f"-- {table}: {len(rows)} satır\n")
        for i in range(0, len(rows), BATCH_SIZE):
            values = ",\n".join("(" + ",".join(sql_value(v) for v in row) + ")" for row in rows[i:i + BATCH_SIZE])
            out.write(f"INSERT INTO {table} ({columns}) VALUES\n{values};\n")
        out.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Mobbing Risk Analizi veritabanı için örnek veri üretir.")
    parser.add_argument("--employees", type=int, default=200, help="çalışan sayısı (en az 60)")
    parser.add_argument("--seed", type=int, default=2025, help="rastgelelik tohumu; aynı tohum aynı veriyi üretir")
    parser.add_argument("--out", default="02_seed.sql", help="yazılacak SQL dosyası")
    args = parser.parse_args()
    if args.employees < 60:
        parser.error("--employees en az 60 olmalı")

    sim = Simulation(args.employees, args.seed).run()
    with open(args.out, "w", encoding="utf-8") as out:
        write_sql(sim, out)
    for table, _ in TABLE_COLUMNS:
        print(f"{table:24s} {len(sim.tables[table]):7d}", file=sys.stderr)


if __name__ == "__main__":
    main()
