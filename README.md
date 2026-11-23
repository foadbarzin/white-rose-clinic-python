# White Rose Clinic — Migration Workspace

**ROSE SEFID BEAUTY CLINIC** · سامانهٔ مدیریت کلینیک · نسخهٔ **0.6.0**
**Developed by FoBa**

---

## وضعیت پروژه

مهاجرت سامانهٔ فعلی (Google Apps Script + Google Sheets، نسخهٔ ۰.۴.۳) به موتور **Python / FastAPI / SQLAlchemy 2.x / Alembic** با حفظ کامل رابط HTML/CSS/JavaScript فعلی.

| فاز | وضعیت |
|---|---|
| Phase 1 — معماری و دامنه | ✅ کامل (`docs/architecture/`) |
| Phase 2 — تثبیت معماری + بنیاد Backend | ✅ نسخهٔ ۰.۵.۰ |
| **Phase 3 — Auth / Users / RBAC / Sessions / Audit** | ✅ همین نسخه (۰.۶.۰) |
| Phase 4+ — پایه‌ها، فاکتور، پورسانت، گزارش، Sync | ⏳ پس از تأیید |

> **هیچ داده‌ای از نسخهٔ قبلی منتقل نشده و هیچ دادهٔ نمونه/Seed ساخته نمی‌شود.**
> پروژهٔ مرجع (`white-rose-clinic` ۰.۴.۳) و نسخهٔ پشتیبان ۰.۴.۱ دست‌نخورده‌اند.

---

## مستندات معماری (مرجع رسمی)

| سند | موضوع |
|---|---|
| [`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md) | معماری کلان، استقرار، فازبندی |
| [`docs/architecture/DOMAIN_MODEL.md`](docs/architecture/DOMAIN_MODEL.md) | ۲۲ ماژول دامنه + اصلاح فاکتور + اعتبار بیمار |
| [`docs/architecture/DATABASE_DESIGN.md`](docs/architecture/DATABASE_DESIGN.md) | ۳۱ جدول، کلیدها، ایندکس‌ها، مبالغ |
| [`docs/architecture/API_DESIGN.md`](docs/architecture/API_DESIGN.md) | قرارداد `POST /api` + همهٔ اکشن‌ها |
| [`docs/architecture/SECURITY_DESIGN.md`](docs/architecture/SECURITY_DESIGN.md) | نشست، RBAC، Audit، SQLCipher/DPAPI |
| [`docs/architecture/OFFLINE_SYNC_DESIGN.md`](docs/architecture/OFFLINE_SYNC_DESIGN.md) | Outbox، تعارض، شمارهٔ موقت |
| [`docs/architecture/MIGRATION_MAPPING.md`](docs/architecture/MIGRATION_MAPPING.md) | نگاشت نسخهٔ قدیم به جدید |
| [`docs/architecture/TECHNICAL_DECISIONS.md`](docs/architecture/TECHNICAL_DECISIONS.md) | TDRها + ثبت نهایی تصمیم‌های مدیر |
| [`docs/architecture/OPEN_ITEMS.md`](docs/architecture/OPEN_ITEMS.md) | موارد باز و نیازمند تصمیم |

---

## ساختار

```text
white-rose-clinic-migration/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                 # create_app + lifespan + middleware
│  │  ├─ api/                    # health, action gateway (/api)
│  │  ├─ core/                   # config, exceptions, logging, security, permissions, dpapi, jalali
│  │  ├─ database/               # base, session, models/
│  │  ├─ schemas/                # پاکت API
│  │  ├─ services/               # use-caseها (فاز ۳+)
│  │  ├─ modules/                # ماژول‌های دامنه (فاز ۳+)
│  │  └─ webui/                  # سرو رابط فعلی
│  ├─ migrations/                # Alembic (env.py + versions/)
│  ├─ tests/                     # pytest
│  └─ alembic.ini
├─ frontend/                     # کپی دست‌نخوردهٔ Client_*.html از پروژهٔ مرجع
├─ docs/architecture/
├─ pyproject.toml
├─ .env.example
├─ VERSION
├─ CHANGELOG.md
└─ README.md
```

---

## راه‌اندازی (توسعه)

```powershell
# 1) محیط مجازی (از قبل موجود است)
.\.venv\Scripts\Activate.ps1

# 2) نصب وابستگی‌ها
python -m pip install -e ".[dev,security,desktop]"

# 3) تنظیمات محلی
Copy-Item .env.example .env
#   → SECRET_KEY را با یک مقدار تصادفی ۴۸ نویسه‌ای جایگزین کنید

# 4) ساخت اسکیمای دیتابیس (SQLite توسعه)
alembic -c backend/alembic.ini upgrade head

# 5) اجرای سرور
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

- رابط فعلی: `http://127.0.0.1:8000/` (همان HTML/CSS/JS نسخهٔ ۰.۴.۳)
- سلامت: `http://127.0.0.1:8000/healthz`
- آمادگی: `http://127.0.0.1:8000/readyz`
- قرارداد واحد: `POST /api` با `{ "action", "payload", "token" }`

---

## راه‌اندازی اولیهٔ امن (Bootstrap)

هیچ حساب مدیر، کاربر نمونه یا رمز پیش‌فرضی در سیستم وجود ندارد. اولین حساب **مالک** فقط با اقدام صریح روی سرور (CLI) ساخته می‌شود و هرگز از طریق API عمومی ممکن نیست:

```powershell
$env:PYTHONPATH = "backend"
python -m app.cli bootstrap-owner --username owner --generate-password --confirm
python -m app.cli status
```

- رمز یک‌بارمصرف فقط یک بار در ترمینال نمایش داده می‌شود و در اولین ورود باید تغییر کند.
- اجرای دوباره پس از وجود کاربر فعال مسدود است.
- می‌توانید به‌جای تولید خودکار، رمز را از stdin بدهید: `--password-stdin`.
- نقش سیستمی `owner` با تمام مجوزها در همین فرمان ساخته می‌شود و قابل ویرایش/حذف نیست.

## سیاست نشست و دسترسی (۰.۶.۰)

- توکن نشست **تصادفی و Opaque** است؛ در دیتابیس فقط `SHA-256` آن ذخیره می‌شود.
- انقضای بی‌کاری **۳۰ دقیقه** و عمر مطلق **۱۲ ساعت**.
- رمزها با **Argon2id** هش می‌شوند (پارامترها در `.env` قابل تنظیم‌اند).
- قفل حساب پس از **۵** تلاش ناموفق برای **۱۵** دقیقه + محدودیت نرخ ورود.
- مجوزها مستقل از نقش‌ها هستند: هر کاربر می‌تواند چند نقش داشته باشد و مجوز مؤثر اجتماع آن‌هاست.
- اعطای مجوزی که خودِ عامل ندارد ممنوع است (ضد ارتقای دسترسی).
- تمام رویدادهای امنیتی در `audit_log` (فقط-افزودنی با زنجیرهٔ هش) ثبت می‌شوند.

```powershell
python -m pytest backend/tests -q
```

پوشش: راه‌اندازی اپ، Health، اعتبارسنجی تنظیمات، اتصال DB، مهاجرت Alembic، قرارداد API، مدیریت خطا، امنیت (توکن/هش/RBAC/DPAPI) و جلالی.

---

## قواعد امنیتی این مخزن

- `SECRET_KEY` و رمزهای واقعی فقط در `.env` محلی (خارج از Git).
- هیچ رمز پیش‌فرض/حساب مدیر Seed نمی‌شود؛ اولین حساب فقط با `python -m app.cli bootstrap-owner` روی سرور ساخته می‌شود (نه از API و نه با wizard/رمز ثابت).
- لاگ‌ها هرگز توکن/رمز/هش را ثبت نمی‌کنند.
- PostgreSQL عملیاتی فقط پس از اجازهٔ مدیر نصب/راه‌اندازی می‌شود.

---

## محدودیت‌های اعلام‌شده

- انتقال دادهٔ نسخهٔ ۰.۴.۳ انجام نشده است (طبق درخواست).
- SQLCipher روی این ایستگاه تست شده، اما پذیرش نهایی ایستگاه‌های کلینیک باز است (`OPEN_ITEMS` O-03).
- اکشن‌های مالی در فاز ۲/۳ با `ACTION_NOT_IMPLEMENTED` پاسخ می‌دهند تا هیچ عملیات واقعی بدون سرویس کامل اجرا نشود.
- از نسخهٔ ۰.۶.۰، احراز هویت/کاربران/RBAC/Audit واقعی و فعال است؛ اولین حساب فقط با CLI ساخته می‌شود.
