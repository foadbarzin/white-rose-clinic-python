# طراحی API — White Rose Clinic (نسخهٔ Python)

> **فاز:** ۱ · **وضعیت:** پیش‌نویس برای تأیید مدیر · **اصل حاکم:** سازگاری کامل با UI فعلی · **Developed by FoBa**
>
> قرارداد واحد نسخهٔ فعلی (`apiCall(action, payload, token)`) حفظ می‌شود. تمام نام اکشن‌ها، فیلدهای payload و شکل پاسخ با نسخهٔ ۰.۴.۳ سازگار می‌مانند؛ افزودن فیلد/اکشن جدید فقط **افزایشی** است.

---

## ۱) قرارداد پایه (بدون تغییر)

### درخواست
```http
POST /api
Content-Type: application/json

{ "action": "invoices.query", "payload": { "status": "issued" }, "token": "<opaque-session-token>" }
```

### پاسخ موفق
```json
{ "ok": true, "data": { } }
```

### پاسخ خطا
```json
{ "ok": false, "error": { "code": "FORBIDDEN", "message": "دسترسی مجاز نیست.", "details": null } }
```

**قواعد:**
- HTTP status همیشه `200` برای خطاهای دامنه (سازگاری با شیم فعلی که فقط JSON را می‌خواند)؛ خطاهای زیرساختی (`502/503`) فقط در قطعی سرویس.
- `token` هم در بدنه و هم در هدر `Authorization: Bearer <token>` پذیرفته می‌شود؛ هدر مقدم است (سازگاری + امکان استفادهٔ ابزارها).
- `payload.token/sessionToken` (رفتار فعلی) پشتیبانی می‌شود.
- `X-Request-Id` اختیاری؛ در نبود آن سرور تولید می‌کند و در پاسخ برمی‌گرداند.
- `X-Idempotency-Key` برای عملیات ایجاد (اختیاری، توصیه‌شده در آفلاین).

### نقطه‌های غیر اکشنی
| مسیر | متد | کاربرد |
|---|---|---|
| `/healthz` | GET | زنده بودن (بدون DB) |
| `/readyz` | GET | اتصال DB + نسخهٔ اسکیما |
| `/api/meta/version` | GET | نسخهٔ اپ و اسکیما |
| `/desktop/info` | GET | سازگاری با `desktop/server.js` فعلی |
| `/` و `/index.html` | GET | سرو UI فعلی (همان `Client_Index`) |
| `/api/v1/*` | * | رزرو برای REST آینده (در فاز ۱ پیاده نمی‌شود) |

---

## ۲) کدهای خطا (پاکت پایدار)

| کد | HTTP معادل | معنا |
|---|---|---|
| `VALIDATION` | 400 | ورودی نامعتبر (پیام فارسی مشخص) |
| `UNAUTHORIZED` | 401 | نشست نامعتبر/منقضی |
| `FORBIDDEN` | 403 | نقش/مالکیت مجاز نیست |
| `NOT_FOUND` | 404 | موجودیت یافت نشد |
| `DUPLICATE` | 409 | تکراری (نام کاربری، شمارهٔ فاکتور) |
| `INVALID_STATE` | 409 | گذار وضعیت مجاز نیست |
| `CONFLICT` | 409 | تعارض نسخه/همگام‌سازی |
| `LOCK_TIMEOUT` | 423 | قفل ردیف/دنباله در دسترس نیست |
| `AUTH_FAILED` | 200 | نام کاربری/رمز نادرست |
| `AUTH_LOCKED` | 200 | حساب موقتاً قفل |
| `RATE_LIMITED` | 429 | تلاش بیش از حد |
| `SYNC_REJECTED` | 200 | عملیات آفلاین رد شد (با جزئیات) |
| `INTERNAL` | 500 | خطای غیرمنتظره (بدون افشای جزئیات) |

---

## ۳) فهرست کامل اکشن‌ها

> ستون «مجوز» مطابق ماتریس `DOMAIN_MODEL.md` است. همهٔ اکشن‌ها به‌جز `PUBLIC` نیازمند نشست معتبرند.

### ۳.۱ عمومی (بدون نشست)
| اکشن | payload | خروجی | محدودیت |
|---|---|---|---|
| `system.ping` | `{}` | `{app, ts}` | — |
| `system.bootstrapStatus` | `{}` | `{hasAdmin, spreadsheetConfigured, pepperConfigured}` | — |
| `auth.login` | `{username, password, deviceInfo}` | `{token, user, mustChangePassword}` | ۵ تلاش/۱۵ دقیقه |
| `setup.bootstrapAdmin` | `{username, password, displayName, setupKey}` | `{ok, user}` | فقط یک‌بار (نبود مدیر فعال) |

### ۳.۲ احراز هویت و کاربر
| اکشن | payload | مجوز |
|---|---|---|
| `auth.me` | `{}` | همه |
| `auth.logout` | `{token}` | همه |
| `auth.changePassword` | `{oldPassword, newPassword}` | همه |
| `users.list` | `{}` | admin |
| `users.create` | `{username, password, displayName, role, linked_doctor_id, linked_operator_id}` | admin |
| `users.update` | `{id, display_name?, role?, linked_*, is_active?}` | admin |
| `users.resetPassword` | `{id, newPassword}` | admin |

### ۳.۳ پایه‌ها
| اکشن | payload | مجوز |
|---|---|---|
| `customers.list` / `customers.create` / `customers.update` / `customers.delete` | فیلدهای بیمار | admin+operator (حذف: admin) |
| `doctors.list` / `.create` / `.update` / `.delete` | فیلدهای پزشک | خواندن: admin+operator؛ نوشتن: admin |
| `operators.list` / `.create` / `.update` / `.delete` | فیلدهای اپراتور | خواندن: admin+operator؛ نوشتن: admin |
| `services.list` / `.create` / `.update` / `.delete` | فیلدهای خدمت + ۴ ستون پورسانت | خواندن: همه؛ نوشتن: admin |
| `settings.get` / `.set` / `.setMany` / `.catalog` | `{key,value}` یا `{values:{}}` | admin |
| `setup.run` | `{}` | admin |

### ۳.۴ فاکتور و پرداخت
| اکشن | payload | خروجی | مجوز |
|---|---|---|---|
| `invoices.list` | `{}` | آرایهٔ فاکتورها (سازگار) | admin/operator؛ پزشک: خودش |
| `invoices.query` | `{status?, from?, to?, limit?, offset?, q?}` | `{rows,total,filtered_count,counts,statuses,filters}` | همان |
| `invoices.get` | `{id}` | `{invoice, items, payments}` | همان |
| `invoices.preview` | `{items[], discount_approved_toman, discount_requested_toman}` | محاسبات بدون ذخیره | admin/operator |
| `invoices.saveDraft` | `{id?, patient_id/customer_id, doctor_id, operator_id, invoice_date, items[], discount_*, notes}` | `{invoice, items, payments}` | admin/operator |
| `invoices.requestDiscount` | `{id, discount_requested_toman, note}` | invoice | admin/operator |
| `invoices.approveDiscount` | `{id, approve:true, discount_approved_toman}` یا `{id, approve:false, reason}` | `{invoice, items, payments}` | admin |
| `invoices.issue` | `{id}` | `{invoice, items, payments}` | admin/operator |
| `invoices.void` | `{id, reason}` | invoice | admin |
| `payments.add` | `{invoice_id, amount_toman, payment_date?, method?, reference_no?, notes?}` | `{payment, invoice}` | admin/operator |

> **سازگاری:** `customer_id` و `patient_id` هر دو پذیرفته می‌شوند؛ پاسخ هم `customer_id` را (برای UI فعلی) و هم `patient_id` را شامل می‌شود.

### ۳.۵ پورسانت
| اکشن | payload | مجوز |
|---|---|---|
| `commissionRules.list` | `{}` | admin |
| `commissionRules.upsert` | `{id?, applies_to, person_id?, service_id?, type, value, priority?, effective_from?, effective_to?, is_active?}` | admin |
| `commissionRules.delete` | `{id}` | admin |
| `commissions.list` | `{status?, from?, to?, person_type?, person_id?, limit?, offset?}` | admin کامل؛ پزشک فقط خودش؛ اپراتور ⛔ |
| `commissions.approvePayable` | `{ids[]}` | admin |
| `commissions.markPaid` | `{ids[], payment_reference}` | admin |

### ۳.۶ مالی
| اکشن | payload | مجوز |
|---|---|---|
| `expenses.list` | `{from?, to?, limit?, offset?}` | admin/operator |
| `expenses.create` | `{date, category, amount_toman, payee, description}` | admin/operator |
| `expenses.delete` | `{id}` | admin |
| `revenue.list` | `{from?, to?}` | admin/operator |
| `revenue.create` | `{date, amount_toman, source_type?, source_id?, description}` | admin |

### ۳.۷ گزارش‌ها
| اکشن | payload | خروجی | مجوز |
|---|---|---|---|
| `reports.dashboard` | `{}` | شاخص‌های نقش‌محور | همه (دامنهٔ نقش) |
| `reports.summary` | `{}` | `{invoice_income, misc_income, income_total, expense_total, net, invoices_by_status, commissions_amount_by_status}` | admin |
| `reports.period` | `{from?, to?, granularity?}` | `{from,to,granularity,buckets[],totals}` | admin |
| `reports.insights` | `{from?, to?, granularity?}` | `{current, previous, deltas, best_day, top_services, alerts[]}` | admin |
| `reports.customers` | `{from?, to?, q?}` | `{rows[], totals, count}` | admin/operator |
| `reports.services` | `{from?, to?}` | `{rows[], totals}` | admin/operator/doctor(خودش) |

**اصلاح H-01 در قرارداد:** همهٔ پاسخ‌های درآمدی فیلد `void_invoice_payments_excluded` (مبلغ حذف‌شده) را برمی‌گردانند تا شفافیت و آزمون‌پذیری تضمین شود.

### ۳.۸ سیستم، پشتیبان و بازیابی
| اکشن | payload | مجوز | توضیح |
|---|---|---|---|
| `system.calendar` | `{}` | همه | تاریخ امروز/هفته/ماه شمسی |
| `system.dataSummary` | `{}` | admin | شمارش ردیف‌ها + طرح حذف |
| `system.exportData` | `{kind?:'full'}` | admin | بکاپ JSON + `checksum_sha256` + `schema_version` |
| `system.backup.list` | `{}` | admin | فهرست فایل‌های پشتیبان + متادیتا |
| `system.backup.create` | `{kind?}` | admin | پشتیبان فوری (فایل + رکورد `backup_jobs`) |
| `system.restore.preview` | `{file_name}` | admin | اعتبارسنجی checksum/نسخه/شمارش **بدون نوشتن** |
| `system.restore.apply` | `{file_name, checksum, confirm:true, phrase}` | admin | بازیابی با بکاپ خودکار پیشین |
| `system.wipeData` | `{confirm:true, phrase:'حذف کلیه اطلاعات'}` | admin | soft-delete گروهی |
| `system.audit.list` | `{entity?, entity_id?, action?, from?, to?, limit?}` | admin | جست‌وجوی Audit |
| `system.audit.verify` | `{from?, to?}` | admin | بررسی زنجیرهٔ هش |
| `system.devices.list` / `.enroll` / `.revoke` | `{label}` / `{id}` | admin | مدیریت Desktop Agent |
| `system.diagnostics` | `{}` | admin | وضعیت DB، صف همگام‌سازی، آخرین بکاپ، خطاهای Audit |

### ۳.۹ همگام‌سازی (دستگاه، نه کاربر)
| اکشن | payload | خروجی |
|---|---|---|
| `sync.handshake` | `{device_id, device_token, app_version, schema_version}` | `{server_time, min_client_schema, pull_cursor, server_node}` |
| `sync.push` | `{device_id, ops:[envelope]}` (حداکثر ۲۰۰) | `{results:[{op_id,status,code?,data?}], next_cursor}` |
| `sync.pull` | `{device_id, cursor, entities?, limit?}` | `{changes:[...], next_cursor, has_more}` |
| `sync.resolveConflict` | `{conflict_id, resolution, note}` | `{status}` |
| `sync.status` | `{device_id}` | `{queue_len, last_push_at, last_pull_at, open_conflicts}` |

**احراز هویت دستگاه:** هدر `X-Device-Id` + `X-Device-Token` (هش‌شده در `devices`). پاکت‌ها باید `actor_user_id` معتبر داشته باشند؛ در آفلاین، آخرین نشست معتبر کاربر محلی مبنای `actor` است و سرور `users.is_active` را بررسی می‌کند.

---

## ۴) قراردادهای داده

| موضوع | قاعده |
|---|---|
| مبالغ | در JSON عدد یا رشته؛ سرور هر دو را می‌پذیرد و **رشته** برمی‌گرداند تا `float` رخ ندهد (حداکثر ۱ اعشار) |
| تاریخ | `YYYY-MM-DD` برای فیلدهای تاریخ؛ زمان‌ها ISO-8601 با منطقه (`...+03:30`) |
| تاریخ شمسی | فقط لایهٔ نمایش؛ API تاریخ شمسی نمی‌پذیرد (به‌جز اکشن `system.calendar` که خروجی شمسی می‌دهد) |
| شمارش | `total` = کل، `filtered_count` = پس از فیلتر، `counts` = به‌تفکیک وضعیت |
| صفحه‌بندی | `limit` (پیش‌فرض ۵۰، حداکثر ۲۰۰) + `offset`؛ پاسخ شامل `has_more` |
| مرتب‌سازی | پیش‌فرض فاکتورها: `invoice_date DESC, created_at DESC` |
| رشتهٔ خالی | `''` = پاک‌کردن مقدار (در ویرایش)؛ `null` = بدون تغییر |
| شناسه | UUID متنی با خط تیره (نسخهٔ ۴ و ۷ پذیرفته می‌شود) |
| نرمال‌سازی | username lowercase؛ موبایل/تلفن طبق قاعدهٔ مرجع؛ trim |

---

## ۵) نمونه‌های قرارداد

### ثبت پیش‌نویس فاکتور (سازگار با UI فعلی)
```json
{
  "action": "invoices.saveDraft",
  "payload": {
    "customer_id": "0b6a...",
    "doctor_id": "5f22...",
    "operator_id": "9c31...",
    "invoice_date": "2026-11-23",
    "discount_requested_toman": 50000,
    "items": [
      { "service_id": "a1...", "quantity": 1, "unit_price_toman": 1200000, "taxable": true },
      { "service_id": "a2...", "quantity": 2, "unit_price_toman": 300000 }
    ]
  }
}
```
پاسخ: `{ ok:true, data:{ invoice:{...}, items:[...], payments:[] } }` با `status: "pending_discount_approval"` (چون تخفیف درخواست شده است).

### پاکت همگام‌سازی
```json
{
  "op_id": "019a1f2c-...",
  "device_id": "3f8e...",
  "device_seq": 1042,
  "entity": "invoices",
  "op_type": "command",
  "entity_id": "9c11...",
  "base_row_version": 3,
  "occurred_at": "2026-11-23T09:15:00+03:30",
  "command": "issue",
  "payload": {}
}
```

### خطای اعتبارسنجی
```json
{ "ok":false, "error":{ "code":"VALIDATION", "message":"تاریخ «از» معتبر نیست.", "details":{"field":"from"} } }
```

---

## ۶) نسخه‌بندی و سازگاری

1. **`/api` پایدار است** و شکستن قرارداد در آن ممنوع؛ تغییرات فقط افزایشی.
2. هر اکشن جدید ابتدا در همین سند ثبت می‌شود (قاعدهٔ «سند قبل از کد»).
3. `/api/v1` برای منابع REST آینده رزرو است؛ هیچ UI فعلی به آن وابسته نیست.
4. سرور `min_client_version` را در `sync.handshake` اعلام می‌کند؛ کلاینت قدیمی‌تر از حد مجاز پیام به‌روزرسانی می‌گیرد.
5. تست قرارداد (snapshot) برای **همهٔ** اکشن‌ها اجباری است تا UI فعلی نشکند.

---

## ۷) نکات امنیتی API

- نرخ‌محدودسازی: `auth.login` حداکثر ۱۰/دقیقه/IP و ۵ تلاش/کاربر؛ اکشن‌های سنگین (`reports.*`) ۶۰/دقیقه/کاربر.
- حداکثر اندازهٔ بدنه: ۱MB (همگام‌سازی: ۲MB با حداکثر ۲۰۰ عملیات).
- `token` هرگز در لاگ یا URL نوشته نمی‌شود.
- خطای `INTERNAL` فقط پیام فارسی عمومی + `request_id`؛ جزئیات در لاگ سرور.
- CORS بسته است (same-origin)؛ Desktop از `127.0.0.1:<port>` همان origin است.
- هر اکشن در سند «مجوز» دارد؛ اکشن بدون مجوز ثبت‌شده اجرا نمی‌شود.

---

## ۸) نگاشت اکشن‌های فعلی → ماژول‌های جدید

| اکشن فعلی (۰.۴.۳) | use-case جدید | تغییر قرارداد |
|---|---|---|
| `customers.*` | `patient_service.*` | هیچ (نام اکشن حفظ می‌شود) |
| `invoices.list` | `invoice_service.list` | افزودن `limit/offset` اختیاری |
| `invoices.query` | `invoice_service.query` | افزودن `q` (جست‌وجو) |
| `payments.add` | `payment_service.add` | افزودن `void` جداگانه |
| `commissions.*` | `commission_service.*` | فیلترهای تاریخ/شخص افزوده |
| `reports.*` | `report_service.*` | `void_invoice_payments_excluded` افزوده |
| `system.exportData` | `backup_service.export` | `checksum_sha256` + `schema_version` |
| `system.wipeData` | `admin_service.wipe` | بدون تغییر (+ بکاپ پیشین) |
| — (جدید) | `backup_service.restore_*` | اکشن‌های جدید |
| — (جدید) | `sync.*` | اکشن‌های جدید |

---

## ۹) اکشن‌های اصلاح فاکتور (TDR-012 — قطعی)

| اکشن | payload | خروجی | مجوز |
|---|---|---|---|
| `invoices.amendments.list` | `{invoice_id}` | `{rows:[amendment]}` | admin |
| `invoices.amendments.get` | `{id}` | `{amendment, items, invoice}` | admin |
| `invoices.amendments.preview` | `{invoice_id, items[], reason}` | محاسبات قبل/بعد و دلتا (بدون ذخیره) | admin |
| `invoices.amendments.create` | `{invoice_id, items[], reason, notes?}` | `{amendment, items}` با `status=draft` | admin |
| `invoices.amendments.update` | `{id, items[], reason?}` | نسخهٔ پیش‌نویس به‌روزشده | admin |
| `invoices.amendments.issue` | `{id}` | `{amendment, invoice, items, commissions}` | admin |
| `invoices.amendments.void` | `{id, reason}` | amendment با `status=void` | admin |

**قواعد قرارداد:**
- `reason` اجباری (≥۳ نویسه) در create/void.
- `preview` دقیقاً همان موتور محاسبهٔ `issue` را اجرا می‌کند (بدون ذخیره).
- پاسخ `issue` شامل `invoice.version` جدید و `amendment.delta_*` است.
- دامنهٔ مجاز: فاکتورهای `issued`/`partially_paid`/`paid`؛ در غیر این صورت `INVALID_STATE`.
- تلاش برای اصلاح فاکتور `void` → `INVALID_STATE`؛ اصلاح تکراری روی همان نسخه → `CONFLICT`.

---

## ۱۰) اکشن‌های اعتبار بیمار (TDR-016 — قطعی)

| اکشن | payload | خروجی | مجوز |
|---|---|---|---|
| `credits.balance` | `{patient_id}` | `{patient_id, balance_toman, last_transaction_at}` | admin؛ operator فقط‌خواندنی |
| `credits.transactions` | `{patient_id, from?, to?, limit?, offset?}` | `{rows, total, sum_in_toman, sum_out_toman}` | admin |
| `credits.adjust` | `{patient_id, direction, amount_toman, reason, idempotency_key}` | `{transaction, account}` | admin |
| `credits.refund` | `{patient_id, amount_toman, method, reference_no, reason}` | `{transaction, account}` | admin (فاز بعد — طراحی‌شده) |

**قواعد قرارداد:**
- `credits.adjust` با `reason` اجباری و `idempotency_key` یکتا؛ تکرار → همان نتیجه (`duplicate:true`).
- موجودی منفی → `VALIDATION` با پیام فارسی.
- اعتبار در پاسخ‌های `reports.summary`/`reports.period` به‌صورت `patient_credit_balance_total` (تعهد/بدهی) و `patient_credit_issued`/`patient_credit_used` برمی‌گردد و هرگز به `income_total` اضافه نمی‌شود.
- `payments.add` با مبلغ بیش از مانده: پاسخ شامل `overpayment_credit` (گردش اعتبار ایجادشده) است؛ رفتار پیش‌فرض = ثبت اعتبار (TDR-016 قطعی).

---

## ۱۱) وضعیت پیاده‌سازی (فاز ۲)

| دسته | پیاده‌سازی فاز ۲ |
|---|---|
| `system.ping`, `system.bootstrapStatus` | ✅ فعال (بدون نیاز به نشست) |
| `GET /healthz`, `GET /readyz`, `GET /api/meta/version`, `GET /desktop/info`, `GET /` | ✅ فعال |
| سایر اکشن‌ها (auth/users/patients/invoices/payments/credits/amendments/reports/system) | قرارداد و مسیر ثبت شده‌اند؛ در فاز ۲ با کد `ACTION_NOT_IMPLEMENTED` پاسخ می‌دهند تا UI فعلی سالم بماند و هیچ عملیات مالی بدون سرویس واقعی اجرا نشود |

**قاعدهٔ حاکم:** «قرارداد کامل، پیاده‌سازی تدریجی». افزودن هر اکشن فقط با ثبت در این سند، تست قرارداد و مجوز مجاز است.



