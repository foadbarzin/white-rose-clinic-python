# نگاشت مهاجرت — White Rose Clinic (نسخهٔ Python)

> **فاز:** ۱ · **وضعیت:** پیش‌نویس برای تأیید مدیر · **Developed by FoBa**
>
> **تصریح مهم:** در این فاز **هیچ داده‌ای منتقل نمی‌شود**. نسخهٔ جدید کاملاً خالی است و فقط «ساختار و قواعد» نسخهٔ مرجع مبنای طراحی است. این سند نگاشت ساختاری/عملکردی و برنامهٔ مهاجرت آیندهٔ داده (در صورت درخواست جداگانهٔ کارفرما) را مستند می‌کند.

---

## ۱) خلاصهٔ نگاشت

| نسخهٔ فعلی | نسخهٔ جدید | وضعیت |
|---|---|---|
| Google Apps Script (`Server_*.gs`) | FastAPI + use-cases دامنه | بازنویسی کامل |
| Google Sheets (۱۷ شیت) | PostgreSQL (سرور) / SQLite (دسکتاپ) | جایگزینی کامل |
| `google.script.run.apiCall` | `POST /api` با همان قرارداد | حفظ |
| HTML/CSS/JS (`Client_*.html`) | همان فایل‌ها (کپی) | حفظ |
| Electron (`desktop/`) | همان پوسته + راه‌انداز سرور Python | حفظ |
| `CacheService` / `LockService` | جدول نشست + قفل ردیف DB | جایگزینی |

---

## ۲) نگاشت جدول‌ها و ستون‌ها

### ۲.۱ `Users` → `users`

| ستون فعلی | ستون جدید | تبدیل |
|---|---|---|
| `id` | `id` | حفظ مقدار (UUID) |
| `username` | `username` | lowercase + trim |
| `password_hash`, `password_salt`, `hash_algo`, `hash_version`, `iterations` | `password_hash` (encoded) یا `password_algo/params` | **بازنویسی هش لازم نیست**: ستون `password_algo='pbkdf2_sha256'` + پارامترها نگه داشته می‌شود؛ در اولین ورود موفق به Argon2id ارتقا |
| `display_name` | `display_name` | — |
| `role` | `role` | همان سه نقش |
| `linked_doctor_id` / `linked_operator_id` | همان | حفظ |
| `is_active` | `is_active` | `'true'` → `true` |
| `must_change_password` | همان | — |
| `failed_attempts`, `locked_until`, `last_login_at` | همان | — |
| audit fields | ستون‌های مشترک | `is_deleted` متنی → boolean |

### ۲.۲ `Customers` → `patients`

| ستون فعلی | ستون جدید | تبدیل |
|---|---|---|
| `id`, `full_name`, `mobile`, `phone`, `national_code`, `birth_date`, `gender`, `address`, `notes`, `status` | همان | `birth_date` ISO → `date`؛ موبایل/تلفن نرمال‌شده |
| API `customers.*` | همان نام اکشن | آداپتور `patient_id ↔ customer_id` |
| حذف نرم | همان | — |

### ۲.۳ `Doctors` / `Operators` / `Services`

| ستون | تبدیل |
|---|---|
| همهٔ فیلدهای فعلی | مستقیم (boolean متنی → boolean) |
| `Services.doctor_commission_type/value`, `operator_commission_type/value` | حفظ می‌شود (همان چهار ستون)؛ برای اپراتور از قید `<=100` روی percent استفاده می‌شود |
| `base_price_toman` | `numeric(18,1)` — مقادیر صحیح بدون تغییر |

### ۲.۴ `Invoices` → `invoices`

| ستون فعلی | ستون جدید | یادداشت |
|---|---|---|
| `id`, `invoice_no`, `invoice_date`, `customer_id` | `id`, `invoice_no`, `invoice_date`, `patient_id` | نام ستون FK تغییر می‌کند؛ مقدار حفظ |
| `doctor_id`, `operator_id` | همان | — |
| `subtotal_toman`, `discount_*`, `tax_toman`, `total_toman`, `paid_toman`, `balance_toman` | همان | `numeric(18,1)` |
| `status` | همان | ۶ مقدار یکسان |
| `issued_at/by`, `void_reason`, `notes`, `amended_from_invoice_id` | همان | — |
| audit + `is_deleted` | ستون‌های مشترک | — |
| — | `invoice_no_provisional` | جدید (آفلاین) |
| — | `invoice_version` | جدید |

### ۲.۵ `InvoiceItems` → `invoice_items`

| ستون فعلی | ستون جدید | یادداشت |
|---|---|---|
| `id`, `invoice_id`, `service_id`, `service_name_snapshot`, `description` | همان | — |
| `quantity`, `unit_price_toman`, `line_gross_toman`, `line_discount_alloc_toman`, `line_net_after_discount_toman`, `effective_tax_rate`, `taxable`, `line_tax_toman`, `line_total_toman`, `commission_basis_toman`, `sort_order` | همان | انواع Decimal |
| `taxable` | boolean | `'true'` → `true` |

### ۲.۶ `Payments` / `Revenue` / `Expenses`

| ستون | تبدیل |
|---|---|
| `Payments.*` | مستقیم؛ `method` در enum چهارمقداری نگاشت می‌شود (`cash`,`card`,`transfer`,`other`؛ مقدار ناشناخته → `other` + هشدار) |
| `Revenue` → `other_income` | مستقیم؛ `status='active'` حفظ |
| `Expenses.*` | مستقیم؛ `amount_toman > 0` |

### ۲.۷ `CommissionRules` / `Commissions`

| ستون فعلی | ستون جدید | یادداشت |
|---|---|---|
| `applies_to`, `person_id`, `service_id`, `type`, `value`, `calc_unit`, `basis_scope`, `priority`, `is_active`, `effective_*` | همان | — |
| `Commissions.rule_id` | `rule_id varchar(64)` | مقدار `service:<id>` هم پشتیبانی می‌شود |
| `invoice_version`, `rate_or_amount_snapshot`, `commission_amount_toman`, `status`, `calculated_*`, `approved_payable_*`, `paid_*`, `voided_or_adjusted_*` | همان | — |
| — | `source_commission_id` | جدید (تعدیل) |

### ۲.۸ `AuditLog` / `Sequences` / `Sessions` / `Settings` / `Meta`

| فعلی | جدید | یادداشت |
|---|---|---|
| `AuditLog.*` | `audit_log` + `hash_prev/hash_self` | در مهاجرت آینده، زنجیره از صفر ساخته می‌شود (Seed هش) |
| `Sequences.key/next_value` | `sequences.key/next_value` | ادامهٔ شماره‌گذاری بدون تکرار؛ کلید `invoice_<year>` |
| `Sessions.*` | `user_sessions` | نشست‌های فعال منتقل نمی‌شوند (کاربران دوباره وارد می‌شوند) |
| `Settings.key/value` | `settings.key/value` + `value_type` | `value_type` از کاتالوگ کد تعیین می‌شود |
| `Meta.schema_version` | `meta.schema_version` | نسخهٔ اسکیمای جدید (مستقل از `2`/`3` فعلی) |

---

## ۳) نگاشت تنظیمات

| کلید فعلی | نوع | پیش‌فرض | رفتار در نسخهٔ جدید |
|---|---|---|---|
| `tax_enabled` | boolean | `true` | همان؛ اثر فقط بر فاکتورهای جدید |
| `tax_default_rate` | number ۰..۱۰۰ | `0` | همان؛ `numeric(5,2)` |
| `invoice_default_taxable` | boolean | `true` | همان |
| `invoice_prefix` | text ۱..۸ | `WRC` | همان؛ الگوی `^[A-Za-z0-9_-]{1,8}$` |
| `discount_requires_admin` | boolean ثابت | `true` | **فقط‌خواندنی**؛ تغییر از UI ممنوع (سیاست کد) |

**کلیدهای جدید پیشنهادی (نیازمند تأیید):** `session_idle_minutes`، `session_max_concurrent`، `backup_retention_days`، `sync_interval_seconds`، `allow_overpayment` (TD-09)، `offline_invoice_numbering` (TD-13).

---

## ۴) نگاشت قواعد تجاری (کد ↔ دامنه)

| قاعدهٔ نسخهٔ فعلی (فایل/تابع) | قاعدهٔ نسخهٔ جدید | ارجاع |
|---|---|---|
| `Utils.roundRial` (گرد به ریال) | `Money.round_rial()` با `Decimal` ROUND_HALF_UP | `TECHNICAL_DECISIONS` TDR-004 |
| `InvoicesSvc.calculate` (ناخالص → تخفیف Largest Remainder → مالیات خطی) | `InvoiceCalculator` با همان ترتیب و همان الگوریتم | `DOMAIN_MODEL` §۷–۹ |
| `CommissionsSvc.pickRule` (۴ سطح اولویت + priority) | `CommissionResolver` با همان امتیازدهی | `DOMAIN_MODEL` §۱۱ |
| `CommissionsSvc.computeAmount` (percent/fixed_per_unit) | `CommissionCalculator` | همان |
| چرخهٔ `calculated → payable → paid` | همان ماشین وضعیت با گارد گذار | همان |
| `Sequences.next` + `LockService` | `SequenceService` + `SELECT FOR UPDATE` | `DATABASE_DESIGN` §۸.۴ |
| `Permissions.can/assert` و `assertAdmin` | ماتریس RBAC + گارد use-case/روتر | `SECURITY_DESIGN` §۴ |
| `Auth` PBKDF2 + pepper + قفل ورود | Argon2id + pepper + قفل ۵/۱۵ | `SECURITY_DESIGN` §۲ |
| `Sessions` در Cache | `user_sessions` جدول + کش اختیاری | `SECURITY_DESIGN` §۳ |
| `Audit.log` silent catch | `AuditService` با سیاست fail-fast | `SECURITY_DESIGN` §۸ |
| `ReportsSvc.period` (باکت شمسی/شنبه) | `ReportPeriodService` با همان الگوریتم جلالی | `DOMAIN_MODEL` §۱۴ |
| `SettingsSvc.CATALOG` + validate | `SettingsCatalog` + Pydantic validators | همان §۱۸ |
| `AdminSvc.wipeData` (soft-delete + عبارت) | همان + بکاپ پیشین + Audit | `DOMAIN_MODEL` §۱۶ |

---

## ۵) نگاشت رابط کاربری و مسیرها

| مسیر (`#route`) | اکشن‌های مصرفی | تغییر |
|---|---|---|
| `#dashboard` | `reports.dashboard`, `reports.period/insights` | بدون تغییر (پاسخ سازگار) |
| `#invoices` | `invoices.query/get/preview/saveDraft/issue`, `payments.add` | افزودن `q/limit/offset` اختیاری |
| `#customers` | `customers.*` | بدون تغییر |
| `#commissions` | `commissions.list/approvePayable/markPaid` | بدون تغییر |
| `#expenses` | `expenses.*` | + `expenses.delete` صریح |
| `#revenue` | `revenue.*` | بدون تغییر |
| `#reports` | `reports.summary/customers/services` | + فیلد `void_invoice_payments_excluded` |
| `#doctors` / `#operators` / `#services` / `#commissionRules` | اکشن‌های تعاریف | بدون تغییر |
| `#users` / `#settings` | `users.*`, `settings.*`, `setup.run` | + `system.diagnostics`, `system.backup.*` |

**قاعده:** هیچ مسیر یا دکمه‌ای حذف نمی‌شود (`REQ-NAV` / ممنوعیت حذف قابلیت). قابلیت‌های جدید (بازیابی، دستگاه‌ها، تعارض‌ها) به‌صورت **افزایشی** در صفحهٔ تنظیمات/مدیریت اضافه می‌شوند.

---

## ۶) پاسخ به یافته‌های ممیزی در سطح محصول

| یافته | اقدام در نسخهٔ جدید | فاز |
|---|---|---|
| `C-01` عدم persistence دسکتاپ | SQLite پایدار + پشتیبان محلی | ۷ |
| `C-02` نبود Restore | `system.restore.*` + checksum | ۸ |
| `H-01` درآمد فاکتور باطل | اصلاح کوئری گزارش + تست | ۶ |
| `H-02` Formula Injection | خروجی CSV امن (Sheets حذف می‌شود) | ۳ |
| `H-03` نشست Cache-only | جدول نشست + fallback | ۳ |
| `H-04` Audit بی‌صدا | fail-fast + زنجیرهٔ هش | ۳ |
| `H-05` تست API غایب | تست قرارداد/مجوز از ابتدا | ۳ |
| `H-06` PDF غیرقطعی | تولید PDF درون‌برنامه‌ای (خارج از فاز ۱) | ۹ |
| `M-01..M-09` | مطابق `SECURITY_DESIGN.md` §۹ | ۳–۸ |

---

## ۷) برنامهٔ مهاجرت داده (آیندهٔ اختیاری — خارج از این فاز)

> اجرای این بخش فقط با **دستور صریح جداگانهٔ کارفرما** و پس از تحویل نسخهٔ ۱ انجام می‌شود. هدف: انتقال دادهٔ عملیاتی موجود (در صورت وجود) با حفظ شناسه‌ها و شمارهٔ فاکتورها.

**گام‌ها:**
1. **Export** از Google Sheets به JSON (با ابزار فقط‌خواندنی) + ثبت `checksum` و شمارش هر شیت.
2. **Normalize:** تبدیل `'true'/'false'` → boolean، تاریخ‌ها → `date`، مبالغ → `Decimal(1)`، موبایل/تلفن → قاعدهٔ مرجع.
3. **Validate:** بررسی یکتایی `username`/`invoice_no`، صحت FKها (پزشک/اپراتور/بیمار/خدمت)، جمع‌های مالی هر فاکتور.
4. **Load** در PostgreSQL با ترتیب وابستگی: `users` → `patients/doctors/operators/services` → `invoices` → `invoice_items` → `payments` → `commission_rules` → `commissions` → `expenses/other_income` → `settings/meta` → `audit_log`.
5. **Reconcile:** مقایسهٔ شمارش/جمع‌ها؛ گزارش اختلاف با قابلیت اصلاح دستی.
6. **Freeze** نسخهٔ قدیم (فقط‌خواندنی) و ثبت در `CHANGELOG`.

**نکات:**
- نشست‌های فعال منتقل نمی‌شوند (ورود مجدد اجباری).
- `Sequences` منتقل می‌شود تا شماره‌گذاری ادامه یابد (بدون تکرار).
- پورسانت‌های پرداخت‌شده با `paid_at` حفظ می‌شوند.
- هش رمز PBKDF2 حفظ و در اولین ورود ارتقا می‌یابد.
- در صورت رد شدن رکورد، کل مهاجرت در یک تراکنش Rollback می‌شود (all-or-nothing) یا در حالت گزارش‌محور، رکورد در `migration_rejects` ثبت می‌شود (نیازمند تصمیم).

---

## ۸) چک‌لیست پیش از شروع فاز ۲

- [ ] تأیید تصمیم‌های TD-01..TD-15 (به‌ویژه TD-05 SQLCipher، TD-09 پرداخت مازاد، TD-13 شمارهٔ موقت).
- [ ] تأیید نگهداشت داده و سیاست Purge.
- [ ] تأیید توپولوژی استقرار (Windows Server/Linux، TLS، پشتیبان).
- [ ] تأیید اینکه **هیچ داده‌ای** از نسخهٔ قبلی منتقل نمی‌شود (طبق درخواست فعلی).
- [ ] مجوز نصب وابستگی‌های فاز پیاده‌سازی (pytest/httpx/argon2-cffi/psycopg/sqlcipher).

---

## ۹) نگاشت جداول جدید (تصمیم‌های قطعی فاز ۲)

| جدول جدید | منبع/دلیل | نگاشت از نسخهٔ ۰.۴.۳ |
|---|---|---|
| `invoice_amendments` | TDR-012 (اصلاح فاکتور) | ندارد (فقط فیلد رزرو `amended_from_invoice_id`) |
| `invoice_amendment_items` | TDR-012 | ندارد |
| `invoice_number_history` | TDR-013 (حفظ شمارهٔ موقت و رسمی) | ندارد |
| `patient_credit_accounts` | TDR-016 (اعتبار بیمار) | ندارد |
| `patient_credit_transactions` | TDR-016 | ندارد |

**تغییرات جداول موجود:**
- `invoices`: `amendment_count`, `last_amendment_id`, `last_amended_at`, `version`, `numbering_state` (`provisional`/`official`).
- `payments`: `credit_transaction_id`, `overpayment_credit_id`, `method` شامل `credit`.
- `patient_credit_accounts.balance_toman` فقط cache؛ منبع حقیقت دفتر گردش.

---

## ۱۰) نگاشت اکشن‌های جدید

| اکشن جدید | use-case | مجوز |
|---|---|---|
| `invoices.amendments.*` | `invoice_amendment_service` | admin |
| `credits.balance` / `.transactions` / `.adjust` / `.refund` | `patient_credit_service` | admin (operator فقط خواندن موجودی) |
| `system.archive.*` / `system.purge.*` | `admin_service` | admin + Audit |

**قاعدهٔ سازگاری:** هیچ اکشن موجودی حذف/تغییر معنایی نمی‌شود؛ اکشن‌های جدید صرفاً افزایشی‌اند.

---

## ۱۱) وضعیت تصمیم‌ها (فاز ۲)

| TDR | وضعیت نهایی | مرجع |
|---|---|---|
| TDR-001 (Sync) | قطعی | `TECHNICAL_DECISIONS` ثبت نهایی |
| TDR-002 (Opaque token) | قطعی | همان |
| TDR-003 (Action API) | قطعی | همان |
| TDR-004 (`NUMERIC(18,1)`) | قطعی | همان |
| TDR-005 (UUIDv7) | قطعی | همان |
| TDR-006 (تعارض بدون ادغام) | قطعی | همان |
| TDR-007 (Outbox) | قطعی | همان |
| TDR-008 (SQLCipher/DPAPI) | **مشروط** به تست ایستگاه هدف | `SECURITY_DESIGN §۱۲` |
| TDR-010 (جلالی داخلی) | قطعی | `app/core/jalali.py` |
| TDR-012 (Amendment) | قطعی — مدل داده در فاز ۲، سرویس با ماژول فاکتور | `OPEN_ITEMS` O-01 |
| TDR-013 (شمارهٔ موقت) | قطعی | `OFFLINE_SYNC_DESIGN §۱۲` |
| TDR-014/015 (بایگانی/Purge) | قطعی — سیاست تفصیلی باز | `OPEN_ITEMS` O-05 |
| TDR-016 (Patient Credit) | قطعی | `DOMAIN_MODEL §۲۲` |

**ممنوعیت:** هیچ داده‌ای از نسخهٔ ۰.۴.۳ منتقل نمی‌شود (طبق درخواست کارفرما)، مگر با دستور صریح جداگانه و پس از تکمیل نسخهٔ ۱ (بخش ۷ همین سند).

