# Changelog — White Rose Clinic (Python Engine)

تمام تغییرهای معنادار این مخزن در این فایل ثبت می‌شود.
قالب: [Keep a Changelog](https://keepachangelog.com/) · نسخه‌بندی: SemVer.

## [0.5.0] — 2026-11-23 — Phase 2: Architecture Finalization + Python Backend Foundation

### Added
- بنیاد Backend با FastAPI 0.165 روی Python 3.13.17 و ساختار ماژولار (`api/`, `core/`, `database/`, `schemas/`, `services/`, `modules/`, `webui/`).
- تنظیمات مرکزی با Pydantic Settings: `APP_NAME`, `APP_VERSION`, `APP_ENV`, `DEBUG`, `API_HOST`, `API_PORT`, `DATABASE_URL`, `SECRET_KEY`, `SESSION_TTL`, `TIMEZONE`.
- `GET /healthz` (status/application/version/environment)، `GET /readyz`، `GET /api/meta/version`، `GET /desktop/info`.
- قرارداد واحد `POST /api` با `{action, payload, token}` و پاکت `{ok, data}` / `{ok:false, error:{code,message,details}}`.
- سرو رابط فعلی (`Client_Index/App/Styles/Logo/LogoMark`) با include resolver و شیم `google.script.run` — **بدون بازطراحی**.
- لایهٔ امنیت: تولید/هش توکن نشست (SHA-256)، هش رمز Argon2id با fallback PBKDF2، RBAC سه‌نقشی + مجوزهای جدید اصلاح فاکتور/اعتبار، DPAPI با `ctypes`.
- ماژول جلالی داخلی (`app/core/jalali.py`) بدون وابستگی خارجی.
- لایهٔ دادهٔ Sync SQLAlchemy 2.x: `Base` + mixinهای UUIDv7/Audit/SoftDelete/Version/Sync، `session_scope`، PRAGMAهای SQLite.
- مدل دادهٔ اولیه: ۲۸ جدول شامل `invoice_amendments`, `invoice_amendment_items`, `invoice_number_history`, `patient_credit_accounts`, `patient_credit_transactions` و جداول همگام‌سازی.
- Alembic با migration اولیهٔ **ساختار فقط** (بدون هیچ Seed/دادهٔ نمونه).
- تست‌های pytest + httpx: startup، health، config، DB، migration، API contract، error handling، security، jalali، DPAPI.
- فایل‌های ریشه: `pyproject.toml`, `.env.example`, `.gitignore`, `VERSION`, `README.md`.
- مستند `docs/architecture/OPEN_ITEMS.md` برای موارد باز.

### Changed
- تثبیت تصمیم‌های مدیر در `docs/architecture/TECHNICAL_DECISIONS.md` (بخش «ثبت نهایی تصمیم‌ها»): Sync ORM، Opaque Session، حفظ قرارداد Action API، `NUMERIC(18,1)` تومان، UUIDv7، تعارض بدون ادغام خودکار، Outbox، SQLCipher+DPAPI، جلالی داخلی، اصلاح فاکتور، شمارهٔ موقت، بایگانی/Purge با Audit، اعتبار بیمار.
- تکمیل `DOMAIN_MODEL.md` با ماژول‌های ۲۱ (اصلاح فاکتور) و ۲۲ (اعتبار بیمار).
- تکمیل `DATABASE_DESIGN.md` با جداول اصلاح فاکتور و اعتبار بیمار + تغییرات `invoices`/`payments`.
- تکمیل `API_DESIGN.md` با اکشن‌های `invoices.amendments.*` و `credits.*` و جدول وضعیت پیاده‌سازی.
- تکمیل `OFFLINE_SYNC_DESIGN.md` با قواعد قطعی شماره‌گذاری و همگام‌سازی اصلاح/اعتبار.
- تکمیل `SECURITY_DESIGN.md` با نتیجهٔ تست SQLCipher، طرح DPAPI، راهکار جایگزین و مجوزهای جدید.
- تکمیل `MIGRATION_MAPPING.md` و `SYSTEM_ARCHITECTURE.md` با وضعیت فاز ۲ و نگاشت جداول جدید.

### Security
- هیچ رمز پیش‌فرض یا حساب مدیر ساخته نشد.
- خطاهای سرور بدون Stack Trace به کلاینت برمی‌گردند (پیام فارسی + `request_id`).
- `SECRET_KEY` نمونه در `.env.example` فقط placeholder است و در `production` رد می‌شود.

### Not changed
- پروژهٔ مرجع ۰.۴.۳، نسخهٔ پشتیبان ۰.۴.۱، پروژهٔ Demo و تنظیمات Cloudflare دست‌نخورده‌اند.
- هیچ داده‌ای منتقل نشد؛ هیچ Push/Deploy انجام نشد.

## [0.1.0] — 2026-11-23 — Phase 1: Architecture & Domain Design
- ایجاد ۸ سند معماری در `docs/architecture/` بر مبنای مطالعهٔ کامل مستندات و کد نسخهٔ ۰.۴.۳ و گزارش ممیزی.
