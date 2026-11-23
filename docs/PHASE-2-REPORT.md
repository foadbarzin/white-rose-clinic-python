# گزارش فاز ۲ — White Rose Clinic Python

**نسخهٔ فاز:** 0.5.0 · **تاریخ:** ۲۰۲۶-۱۱-۲۳ · **نوع سند:** گزارش تاریخی (Historical Record) · **Developed by FoBa**

> این سند وضعیت **پایان فاز ۲** را ثبت می‌کند و عمداً از وضعیت فعلی (نسخهٔ ۰.۶.۰ / فاز ۳) جدا نگه داشته شده است. هیچ قابلیت فاز ۳ در این گزارش به فاز ۲ نسبت داده نمی‌شود. نسخهٔ جاری پروژه همچنان `0.6.0` است و این سند فقط یک مستند تاریخی افزوده است.

---

## ۱) معرفی فاز ۲ و هدف آن

**فاز ۲ — «تثبیت معماری + بنیاد Backend»** با هدف تبدیل طراحی فاز ۱ به یک اسکلت اجرایی واقعی Python انجام شد؛ بدون پیاده‌سازی عملیات مالی و بدون انتقال داده.

اهداف اجرایی:
1. تثبیت تصمیم‌های معماری فاز ۱ با تأیید صریح مدیر (TDRها).
2. ساخت اسکلت FastAPI + SQLAlchemy 2.x (Sync) + Alembic.
3. پیاده‌سازی Health API و حفظ قرارداد واحد `POST /api {action,payload,token}`.
4. سرو همان رابط HTML/CSS/JS فعلی بدون بازطراحی.
5. پیاده‌سازی مدل دادهٔ کامل (۲۸ جدول) با مهاجرت اولیهٔ **فقط DDL** و بدون هیچ Seed.
6. فراهم‌کردن امنیت پایه (Settings، Opaque Session primitives، RBAC matrix، DPAPI) **بدون** ساخت حساب مدیر یا رمز پیش‌فرض.
7. نوشتن و اجرای تست‌های واقعی برای اسکلت.

**خارج از دامنهٔ فاز ۲:** احراز هویت عملیاتی، مدیریت کاربران/نقش‌ها، Audit عملیاتی، هر عملیات مالی (فاکتور/پرداخت/پورسانت/اعتبار)، PostgreSQL عملیاتی و استقرار.

## ۲) تصمیم‌های معماری و فنی نهایی (فاز ۲)

| موضوع | تصمیم تثبیت‌شده |
|---|---|
| ORM | SQLAlchemy **Sync** با `Session` و `session_scope` (TDR-001) |
| نشست | **Opaque Session Token**؛ فقط هش SHA-256 ذخیره می‌شود (TDR-002) |
| API | حفظ `POST /api` با `{action, payload, token}` و پاکت `{ok, data|error}` (TDR-003) |
| پول | `Decimal` + `NUMERIC(18,1)` تومان؛ گرد کردن به ریال صحیح (TDR-004) |
| شناسه | UUIDv7 تولیدشده در کلاینت (TDR-005) |
| تعارض | تعارض مالی بدون ادغام خودکار؛ صف تصمیم مدیر (TDR-006) |
| آفلاین | Transactional Outbox + idempotency (TDR-007) |
| تاریخ | الگوریتم جلالی داخلی بدون وابستگی (TDR-010) |
| دسکتاپ | SQLCipher + Windows DPAPI، **مشروط به تست سازگاری** (TDR-008) |
| شماره فاکتور | موقت آفلاین، رسمی پس از تأیید سرور (TDR-013) |
| بایگانی/Purge | فقط با مجوز مدیر و Audit (TDR-014/015) |
| اعتبار بیمار | `overpayment` به‌عنوان اعتبار، نه درآمد (TDR-016) |
| اصلاح فاکتور | فاکتور صادرشده بدون سابقه تغییر نمی‌کند (TDR-012) |

> مرجع کامل: [`architecture/TECHNICAL_DECISIONS.md`](architecture/TECHNICAL_DECISIONS.md) — بخش «ثبت نهایی تصمیم‌ها» و «ثبت تصمیم‌های فاز ۲».

## ۳) تصمیم‌های قطعی مدیر و میزان تحقق در فاز ۲

### TDR-013 — شمارهٔ موقت فاکتور آفلاین
- **تصمیم:** UUID ثابت فاکتور؛ شمارهٔ موقت `TMP-<node_code>-<seq>` در آفلاین؛ شمارهٔ رسمی `PREFIX-YYYY-NNNNNN` فقط در سرور با قفل ردیف؛ حفظ هر دو شماره در تاریخچه؛ Retry تکراری نمی‌سازد.
- **تحقق فاز ۲:** طراحی و قواعد در `OFFLINE_SYNC_DESIGN` §۱۲ ثبت شد؛ ستون‌های `invoice_no_provisional`، `numbering_state` و جدول `invoice_number_history` در مدل/مهاجرت ساخته شدند. **سرویس صدور و شماره‌گذاری در فاز ۲ پیاده نشد** (وابسته به ماژول فاکتور).

### TDR-016 — اعتبار بیمار (Patient Credit)
- **تصمیم:** مبلغ اضافهٔ پرداخت به‌عنوان اعتبار ثبت شود؛ اعتبار درآمد نیست؛ هر گردش رکورد مستقل با UUID و Audit؛ استفادهٔ اتمی؛ idempotent؛ موجودی = جمع گردش‌ها؛ گزارش جدا؛ بازپرداخت قابل توسعه.
- **تحقق فاز ۲:** مدل دادهٔ `patient_credit_accounts` و `patient_credit_transactions` (با CHECKهای مبلغ/جهت/idempotency) و قواعد در `DOMAIN_MODEL §۲۲` و `DATABASE_DESIGN §۱۷` آماده شد. **سرویس و API اعتبار در فاز ۲ پیاده نشد.**

### TDR-012 — اصلاح فاکتور در فاز ۲
- **تصمیم:** فاکتور صادرشده بدون سابقه تغییر نکند؛ علت اجباری؛ تاریخچه؛ Audit؛ عدم بازنویسی بی‌صدا؛ مجوز مشخص.
- **تحقق فاز ۲:** جدول‌های `invoice_amendments` و `invoice_amendment_items` + ستون‌های نسخه‌بندی فاکتور (`version`, `amendment_count`, `last_amendment_id`, `last_amended_at`) و قواعد کامل در `DOMAIN_MODEL §۲۱` و `API_DESIGN §۹` طراحی و در مهاجرت ساخته شدند.
- **محدودیت صریح:** گردش‌کار عملیاتی اصلاح (سرویس + اکشن‌ها) در فاز ۲ **پیاده‌سازی نشد** و به ماژول فاکتور موکول شد؛ این موضوع در آن زمان به‌عنوان مورد باز `O-01` ثبت و برای تأیید مدیر اعلام شد. بنابراین «اصلاح فاکتور» در پایان فاز ۲ فقط **مدل داده و قواعد** بود، نه قابلیت اجرایی.

### TDR-008 — SQLCipher + DPAPI
- **تصمیم:** رمزنگاری SQLite با SQLCipher و حفاظت کلید با Windows DPAPI؛ تا موفقیت تست، قابلیت «تکمیل‌شده» اعلام نشود.
- **تحقق فاز ۲:** تست واقعی روی ایستگاه توسعه انجام شد (بخش ۹). نتیجه: **موفق روی ایستگاه توسعه**؛ **پذیرش ایستگاه‌های کلینیک انجام نشد** و `O-03` باز ماند.

### TDR-014/015 — بایگانی و Purge
- **تصمیم:** بایگانی/حذف دائمی فقط با مجوز مدیر و ثبت Audit؛ Audit هرگز Purge نمی‌شود؛ رکورد دارای وابستگی مالی Purge نمی‌شود؛ دوره‌های نگهداشت نیازمند تأیید.
- **تحقق فاز ۲:** سیاست در `SECURITY_DESIGN §۱۳` و `TECHNICAL_DECISIONS` ثبت شد؛ ستون‌های حذف نرم و Audit آماده بودند. **اسکریپت/سرویس عملیاتی بایگانی و Purge در فاز ۲ وجود نداشت** (خارج از دامنه؛ جزئیات در `O-05`).

## ۴) ساختار پروژه و فایل‌های ایجادشده در فاز ۲

```text
white-rose-clinic-migration/
├─ .venv/                         # محیط مجازی (خارج از Git)
├─ backend/
│  ├─ app/main.py                 # create_app + lifespan + middleware
│  ├─ app/api/{health,router}.py  # Health و دروازهٔ اکشن
│  ├─ app/core/{config,exceptions,logging,security,permissions,dpapi,jalali}.py
│  ├─ app/database/{base,session}.py + models/{system,identity,base_data,invoicing,finance,sync}.py
│  ├─ app/schemas/api.py
│  ├─ app/services/__init__.py    # placeholder (بدون منطق دامنه)
│  ├─ app/modules/__init__.py     # placeholder
│  ├─ app/webui/renderer.py       # سرو رابط فعلی + شیم apiCall
│  ├─ migrations/{env.py,script.py.mako,versions/20261123_1752_a1ff7456e1a9_initial_schema.py}
│  ├─ alembic.ini
│  └─ tests/                      # ۱۱ ماژول تست
├─ frontend/                      # کپی بدون تغییر Client_Index/App/Styles/Logo/LogoMark + assets/logo.svg
├─ docs/architecture/             # ۹ سند (۸ سند فاز ۱ + OPEN_ITEMS)
├─ pyproject.toml
├─ .env.example · .gitignore · README.md · VERSION · CHANGELOG.md
```

**نکته:** در پایان فاز ۲، `app/services/` و `app/modules/` عمداً خالی بودند تا هیچ منطق مالی/کاربری بدون طراحی کامل اجرا نشود. مدل داده اما کامل بود (۲۸ جدول).

## ۵) فناوری‌ها و نسخهٔ پکیج‌ها (وضعیت همان فاز)

| مورد | نسخه |
|---|---|
| Python | **3.13.17** (64-bit) |
| FastAPI | **0.165.0** |
| Starlette / Uvicorn | 1.10.0 / 0.54.0 (`uvicorn[standard]`) |
| SQLAlchemy | **2.1.9** (Sync) |
| Alembic | **1.20.1** |
| Pydantic / pydantic-settings | **2.14.4** / **2.16.3** |
| python-dotenv / PyYAML | 1.2.4 / 6.0.4 |
| pytest / httpx | 9.2.0 / 0.28.1 (نصب در فاز ۲) |
| argon2-cffi | 25.1.0 (نصب در فاز ۲) |
| psycopg (+binary) | 3.3.9 (درایور هدف PostgreSQL؛ بدون راه‌اندازی سرور) |
| sqlcipher3-wheels | 0.5.7 (`cp313-win_amd64`) |
| SQLCipher runtime | **3.51.1** |

> هیچ PostgreSQL عملیاتی نصب/راه‌اندازی نشد؛ SQLite توسعه (`var/wrc-dev.db`) استفاده شد که در Git Track نمی‌شود.

## ۶) FastAPI و APIهای Health / Ready / Ping

| مسیر | رفتار در فاز ۲ |
|---|---|
| `GET /healthz` | `{status, application, version, environment}` — بدون DB |
| `GET /readyz` | اتصال DB + `schema_version` (از `meta` یا fallback به `alembic_version`)؛ در نبود DB → 503/degraded |
| `GET /api/meta/version` | `{application, version, environment, api_contract:"action-v1", timezone}` |
| `GET /desktop/info` | سازگاری با شل دسکتاپ (`desktop:false, mode:"server"`) |
| `POST /api` | قرارداد واحد اکشن‌محور |

**اکشن‌های عمومیِ پیاده‌شده در فاز ۲ (فقط ۳ مورد):**
- `system.ping` → نام/نسخه/منطقهٔ زمانی + تاریخ
- `system.bootstrapStatus` → `hasAdmin` (همیشه false چون هیچ حسابی ساخته نشده بود)، `databaseReady`، `bootstrapAvailable`
- `system.calendar` → تاریخ امروز/هفتهٔ شنبه‌محور/ماه شمسی

**سایر اکشن‌ها:** اکشن‌های مستند اما پیاده‌نشده (مثل `auth.login`) → `ACTION_NOT_IMPLEMENTED`؛ اکشن‌های محافظت‌شده → `UNAUTHORIZED` چون زیرساخت نشست هنوز عملیاتی نبود. هیچ عملیات مالی اجرا نمی‌شد.

## ۷) دیتابیس و SQLAlchemy

- `Base` با naming convention، mixinهای `UUIDPrimaryKey` (UUIDv7)، `Timestamp` (`row_version` برای optimistic lock)، `SoftDelete`, `SyncColumns`.
- `session.py`: `build_engine`، `get_engine` کش‌شده، `session_scope` (commit/rollback)، `get_session`، `check_connection`، PRAGMAهای SQLite (`foreign_keys=ON`, `busy_timeout`, `WAL`, `synchronous=NORMAL`) و `build_sqlcipher_engine` برای دسکتاپ.
- مبالغ `Numeric(18,1)` با `Decimal`؛ درصد `Numeric(5,2)`؛ JSON عمومی (روی PG به `jsonb`)؛ `Uuid` سازگار با PG/SQLite.
- **۲۸ جدول** شامل پایه‌ها، فاکتور/اقلام/پرداخت، اصلاح فاکتور، پورسانت، مالی، اعتبار بیمار، Audit، Sequences، Devices، Backup و همگام‌سازی.
- هیچ دادهٔ نمونه/Seed در DB ساخته نشد (تست اختصاصی خالی‌بودن جدول‌ها).

## ۸) Migration اولیهٔ Alembic

| مورد | مقدار |
|---|---|
| فایل | `backend/migrations/versions/20261123_1752_a1ff7456e1a9_initial_schema.py` |
| Revision | **`a1ff7456e1a9`** |
| محتوا | فقط DDL: ساخت ۲۸ جدول + ایندکس/قیدها |
| Seed | **هیچ** (بدون داده یا نقش/کاربر) |
| تست‌شده | `upgrade head` → `downgrade base` → `upgrade head` (تکرارپذیر) |
| نسخهٔ اسکیما | ثبت در `alembic_version`؛ `meta.schema_version` در فاز ۲ Seed نشد (آماده برای Setup بعدی) |

> اصلاحیهٔ لازم در همین فاز: تابع `btrim` در CHECKها روی SQLite موجود نیست؛ به `trim` تغییر یافت تا مهاجرت روی هر دو موتور کار کند.

## ۹) نتیجهٔ واقعی تست SQLCipher و DPAPI روی ایستگاه توسعه

### SQLCipher
| آزمون | نتیجه |
|---|---|
| نصب `sqlcipher3-binary` | ❌ برای این پلتفرم توزیعی ندارد (`from versions: none`) |
| نصب `sqlcipher3-wheels` | ✅ نسخهٔ **0.5.7** با wheel `cp313-win_amd64` |
| نسخهٔ کتابخانهٔ SQLCipher | **3.51.1** |
| ساخت DB رمزنگاری‌شده و بازخوانی با همان کلید | ✅ |
| رد کلید اشتباه | ✅ |
| عدم امکان خواندن فایل با `sqlite3` استاندارد | ✅ |
| کارکرد `build_sqlcipher_engine` با SQLAlchemy | ✅ |
| رد کلید کوتاه (≠۳۲ بایت) | ✅ (ValueError) |

### Windows DPAPI
- پیاده‌سازی با `ctypes` (`CryptProtectData`/`CryptUnprotectData`) بدون وابستگی خارجی.
- تست‌های موفق: roundtrip، وابستگی به entropy، رد بلاب دست‌کاری‌شده، پایداری `load_or_create_key` و **عدم ذخیرهٔ کلید به‌صورت متن** (۴ تست PASS).
- مسیر کلید: `%LOCALAPPDATA%\WhiteRoseClinic\keys\db.key.dpapi` (طرح).

**وضعیت اعلامی در پایان فاز ۲:** SQLCipher+DPAPI روی **ایستگاه توسعه** موفق و آزمون‌شده بود؛ **پذیرش روی ایستگاه‌های واقعی کلینیک انجام نشده بود** و به‌عنوان `O-03` باز ماند. بنابراین قابلیت «تکمیل‌شده برای استقرار» اعلام نشد.

## ۱۰) نحوهٔ سرو رابط فعلی و حفظ Frontend

- فایل‌های `Client_Index/App/Styles/Logo/LogoMark` و `assets/logo.svg` **بدون تغییر** از پروژهٔ مرجع کپی شدند (پروژهٔ مرجع دست‌نخورده).
- `app/webui/renderer.py`: حل scriptletهای `<?!= include('...') ?>` و `JSON.stringify(include(...))`، تزریق شیم `google.script.run.apiCall` که همان درخواست را به `POST /api` می‌فرستد.
- مسیر `GET /` صفحهٔ فعلی RTL را سرو می‌کند؛ `GET /assets/logo.svg` لوگو را برمی‌گرداند؛ `GET /favicon.ico` پاسخ 204.
- UI بازطراحی نشد؛ تمام ۱۲ مسیر قبلی (`dashboard`, `invoices`, `customers`, `commissions`, `expenses`, `reports`, `doctors`, `operators`, `services`, `commissionRules`, `users`, `settings`) در فایل باقی ماندند و با تست بررسی شدند.
## ۱۱) تست‌ها و نتایج واقعی فاز ۲

| مورد | مقدار |
|---|---|
| مجموع تست‌های اجراشده | **۸۴** |
| PASS | **۸۴** |
| FAIL / ERROR | **۰** |
| ماژول‌های تست | ۱۱ |
| اجرا | `python -m pytest backend/tests -q` روی **SQLite موقت** |
| دادهٔ واقعی | هیچ تستی به داده/سرویس واقعی کلینیک دسترسی نداشت |
| Mock | Mock صرفاً برای خطاهای زیرساختی؛ مسیرهای DB/مهاجرت/امنیت واقعی اجرا شدند |

**تفکیک ماژول‌ها:**

| ماژول | موضوع |
|---|---|
| `test_app_startup.py` | ساخت اپ، `/healthz`، `/readyz`، متادیتا، OpenAPI |
| `test_config.py` | اعتبارسنجی Settings (env، secret، timezone، PostgreSQL URL، production hardening) |
| `test_database.py` | Engine/Session، UUIDv7، تراکنش/rollback، خالی‌بودن DB، FK، نوع مبالغ |
| `test_migration.py` | `upgrade head`، `downgrade base`، تکرارپذیری، نبود Seed |
| `test_api_contract.py` | پاکت `{ok,...}`، اکشن‌های عمومی، خطاها، عدم افشای Stack Trace |
| `test_errors.py` | خطای 500 عمومی، پاکت `FORBIDDEN`، اعتبارسنجی 422 |
| `test_security.py` | توکن/هش رمز، RBAC legacy، SessionPolicy |
| `test_jalali.py` | نوروز، roundtrip، مرز ماه شمسی، هفتهٔ شنبه‌محور |
| `test_dpapi.py` | DPAPI (۴ تست، فقط Windows) |
| `test_sqlcipher.py` | SQLCipher (۵ تست) |
| `test_webui.py` | سرو UI، شیم، حفظ مسیرها، برند، هدرها |

> ۸۲ تابع تست وجود داشت و یک تست پارامتری با ۳ حالت اجرا شد → **۸۴ تست اجراشده**. پوشش درصدی (coverage) در فاز ۲ اندازه‌گیری/ثبت نشد.

## ۱۲) محدودیت‌ها و موارد باز همان زمان

| محدودیت | وضعیت پایان فاز ۲ |
|---|---|
| احراز هویت عملیاتی (login/users/roles/sessions) | ⛔ پیاده نشده بود؛ `auth.login` → `ACTION_NOT_IMPLEMENTED` |
| Audit عملیاتی | ⛔ فقط جدول/طرح؛ سرویس Audit در فاز ۳ آمد |
| عملیات مالی (فاکتور/پرداخت/پورسانت/اعتبار) | ⛔ هیچ اکشن مالی عملیاتی نبود |
| اصلاح فاکتور (TDR-012) | فقط مدل داده/قواعد؛ سرویس در فاز بعد (`O-01`) |
| اعتبار بیمار (TDR-016) | فقط مدل داده/قواعد |
| شماره‌گذاری فاکتور (TDR-013) | فقط قواعد + ستون‌ها/تاریخچه |
| SQLCipher روی ایستگاه کلینیک | ❌ انجام نشده (`O-03`) |
| PostgreSQL عملیاتی / TLS | ❌ نصب/راه‌اندازی نشد (`O-06`) |
| Rate limiter چندنمونه‌ای / WORM Audit | در آن زمان مطرح/ثبت نشده بود |
| نسخهٔ UI از سرور | هنوز تزریق مستقیم نسخه در HTML انجام نشده بود (فاز ۳) |
| فایل گزارش فاز ۲ | در آن زمان وجود نداشت؛ همین سند بعداً به‌عنوان مستند تاریخی افزوده شد |

**موارد باز ثبت‌شدهٔ آن فاز (`OPEN_ITEMS`):** `O-01` محدودهٔ سرویس اصلاح فاکتور، `O-02` تعدیل پورسانت پس از پرداخت، `O-03` پذیرش SQLCipher روی ایستگاه‌ها، `O-04` نگهداری کلید/بکاپ، `O-05` جزئیات بایگانی/Purge، `O-06` استقرار PostgreSQL/TLS، `O-07` بازپرداخت اعتبار، `O-08` نمایش اعتبار در گزارش‌ها، `O-09` تأیید TTL نشست، `O-10` دامنهٔ تغییرات UI، `O-11` عدم انتقال داده (بسته)، `O-12` بسته‌بندی Desktop، `O-13` چند شعبه، `O-14` تولید PDF.

## ۱۳) ساختار Git و Commitهای Phase 1 و Phase 2

در جریان فاز ۲، مخزن مستقل محلی مقداردهی شد:

```text
main
└─ f9de12f  docs(architecture): phase 1 architecture and domain design
migration/python-foundation
└─ ea60d61  feat(backend): phase 2 python foundation (fastapi, sqlalchemy sync, alembic, security)
```

- Commit فاز ۲: **`ea60d612e172236251fa2b122a08d1761c246325`** (پیام: `feat(backend): phase 2 python foundation (fastapi, sqlalchemy sync, alembic, security)`).
- Branch کاری: `migration/python-foundation`؛ `main` در آن زمان روی Commit فاز ۱ بود.
- Remote در پایان فاز ۲: **تنظیم نشده بود** و **هیچ Push/Deploy** انجام نشد.
- `.env`، `.venv`، دیتابیس‌ها و کلیدها Track نشدند (`.gitignore` از فاز ۲).

> Commit فاز ۳ (`feat(auth): ...`) و انتشار GitHub بعداً در نسخهٔ ۰.۶.۰ انجام شد و جزء فاز ۲ نیست.

## ۱۴) حفاظت از پروژهٔ اصلی ۰.۴.۳ و Backup نسخهٔ ۰.۴.۱

- پروژهٔ مرجع `white-rose-clinic` (نسخهٔ ۰.۴.۳) **هیچ تغییری** نکرد؛ در پایان فاز ۲ وضعیت `main...origin/main [ahead 13]` و بدون تغییر بود.
- نسخهٔ پشتیبان ۰.۴.۱ و پوشهٔ Demo و تنظیمات Cloudflare دست‌نخورده ماندند.
- هیچ رمز/تنظیمات/دادهٔ واقعی تغییر نکرد و **هیچ داده‌ای از نسخهٔ قبلی منتقل نشد**.
- `frontend/` فقط **کپی** فایل‌های رابط از پروژهٔ مرجع بود؛ منبع تغییر نکرد.
- هیچ اتصال عملیاتی، نصب PostgreSQL یا Deploy انجام نشد.

## ۱۵) جمع‌بندی و وضعیت پایان فاز ۲

- اسکلت اجرایی FastAPI + SQLAlchemy Sync + Alembic ساخته شد و **۸۴/۸۴ تست سبز** بود.
- مدل دادهٔ کامل (۲۸ جدول) با مهاجرت **`a1ff7456e1a9`** و بدون هیچ Seed آماده شد.
- قرارداد `POST /api` و سرو رابط فعلی بدون بازطراحی محقق شد؛ اما در این فاز فقط سه اکشن عمومی (`system.ping`, `system.bootstrapStatus`, `system.calendar`) واقعی بودند.
- SQLCipher + DPAPI روی **ایستگاه توسعه** تست موفق داشت (SQLCipher 3.51.1، wheels 0.5.7)؛ پذیرش ایستگاه‌های کلینیک باقی ماند.
- تصمیم‌های مالی/آفلاین (اصلاح فاکتور، اعتبار بیمار، شمارهٔ موقت، بایگانی/Purge) در سطح **مدل داده و قواعد** تثبیت شدند، نه قابلیت اجرایی.
- **وضعیت:** بنیاد فنی آماده و قابل اتکا برای شروع فاز ۳ (احراز هویت/RBAC/Audit) بود؛ نه آمادهٔ استفادهٔ عملیاتی/مالی.

**Developed by FoBa** · White Rose Clinic Python · Phase 2 (0.5.0) — Historical Record



