# Implementation Plan — 外幣自動換算 + 總覽 重新設計

Repo: `/home/ythuang/YTH_personal/expense-dashboard` · Streamlit 1.55.0 (verified in `expense_env`) · Google Sheet GID 453361449, 9 columns, ~2,065 rows · two phone users (菇菇, 過兒).

Synthesis: currency converter = design C (💱 外幣即時換算, phone-first) as the base, grafting B's migration script / explicit-blank writes / 保留原台幣金額 / 換算不一致 audit / orig_amount in the duplicate signature, and A's `(currency, quote_date)` widget key and "no network from 總覽 or when 國家=台灣". 總覽 = design 1 (三秒總覽) with grafts from 2 (上次使用 rate tier, negative cache, Decimal half-up, trip badge) and 3 (copy-sheet rehearsal runbook, COMPARISON_LABEL map, 查看 button, list footer, raw-vs-canonical categories). All critic gaps (G1–G15) are addressed; a cross-reference table is at the end.

---

## 1. Goals & non-goals

### Feature A — 外幣換算 (currency converter)
Goals
- In a shop abroad: pick nothing extra when 國家 is already set; type the foreign amount, see `≈ NT$` before saving, save. Second purchase of a trip = 3 taps + 2 typings.
- `金額` stays an integer TWD and the single source of truth; every existing total, chart, duplicate guard and `_row_matches` is arithmetically unchanged.
- Every converted row is auditable: 幣別, 原幣金額 and the 匯率 actually used are stored next to it; invariant `金額 == to_twd(原幣金額, 匯率)` (±1) holds for every converted row.
- Works with no FX API (stale/static/last-used rate, always editable), and with an un-migrated sheet (saves TWD, warns).
- Later one-field reconciliation against the card statement (帳單金額).

Non-goals
- No automatic back-fill of the ~220 hand-converted historical foreign rows (optional manual back-fill via 編輯 that never moves totals).
- No card-fee modelling beyond a +1.5% toggle; no intraday rates; no Bank of Taiwan source (bot-challenge blocks datacenter IPs).
- No second worksheet, no stable-ID column, no change to `auth.py`.
- No 匯率來源 column in v1 (see §6 Q4).

### Feature B — 總覽 refinement
Goals
- On a 390 px phone the first screen answers "今天／本期花了多少、比上期多或少、誰花的、花在哪" with 1 tap (the tab) and 0 scrolls; default period 本月.
- One period control, one statement of the comparison window, no developer numbers (筆記錄, 平均單筆) on the first screen; charts never capture finger drags; no nested/horizontal scrollers.
- Converted rows visible (原幣 column, per-currency chip) without changing any total.
- Trips reachable in ≤ 2 taps.

Non-goals
- No budget/pace-target feature beyond a caption; no per-user settings; no PWA/offline logging; no change to the 新增/編輯 tab layout other than the FX card.
- No sheet writes from the dashboard (category/location canonicalisation is display-only).

---

## 2. Currency converter

### 2.1 User flow on the phone (新增 tab)

Buying a SGD 12.50 coffee in Singapore, second purchase of the trip:

1. App opens on 新增. Outside the form (as today): 類型 ✈️ 旅行, 分類, 📍 國家 新加坡, 地點 新加坡 — all persisted from the previous entry.
2. Because `COUNTRY_CURRENCY.get(國家, "TWD") != "TWD"`, the **💱 外幣換算** card is rendered directly under 地點 (still outside `st.form`), stacked (G6 — no CSS grid for widgets; `st.columns` stacks < 640 px):
   - `幣別` selectbox, showing **SGD**.
   - `原幣金額 (SGD)` number_input, empty, numeric keypad. User types `12.5`, taps outside → one rerun (~1 s; same mechanic as 地點 following 國家 today). First-use caption: 「輸入後點空白處即更新台幣」.
   - `st.metric` **≈ NT$ 316** (big; display element, never a keyed widget).
   - caption: 「匯率 25.2816（含手續費）· ✅ Frankfurter 2026-09-08」 — one of ✅ 今日匯率 / 🕒 快取 (age) / 🔁 上次使用 09/07 / ⚠️ 離線匯率 2026-09-08. If the source was open.er-api the mandatory link 「Rates By Exchange Rate API」 is appended.
   - `▸ 進階` expander (collapsed): `匯率 (1 SGD = ? TWD)` number_input (editable), `信用卡結匯 +1.5%` toggle, `↻ 重新取得匯率` button.
3. Inside the form (unchanged order): 日期 (today), 帳戶, then **instead of 金額** an `st.info` line 「金額 (TWD)：NT$316 ← SGD 12.50 × 25.2816」; 描述 「咖啡」; 備註; 💾 儲存支出.
4. Flash: 「✅ 成功新增支出: 咖啡 - SGD 12.50 ≈ NT$316」. 原幣金額 clears (key carries `gen`); 幣別 / 匯率 / fee toggle persist for the trip (keyed by country / currency, see §2.2).

First purchase of the trip: +2 taps (國家 ▾ → 新加坡); the rate is fetched during that rerun (spinner 「取得匯率中…」, worst case 12 s — G9), so the quote is cached before the amount is typed.

Domestic (國家 = 台灣) or 幣別 = TWD: the card is not rendered; the in-form 金額 number_input is exactly today's. Zero new widgets, zero network calls.

TWD purchase abroad (Taiwan card in a shop that charges TWD, or cash brought from home): set 幣別 → TWD in the card; the in-form 金額 returns; the row saves as TWD-native (blank J..L).

### 2.2 Widget layout and Streamlit state rules (`input_forms.py`)

Everything FX-related lives OUTSIDE `st.form` (in-form widgets deliver only on submit; `on_change` is forbidden in forms, `policies.py:53`). New helper:

```
_fx_block(kp: str, country: str, gen: int, *, stored: FxStored | None = None,
          on_date: date, show_statement: bool = False) -> FxState | None
```
returns `None` when no conversion is active. `FxState = (currency, orig_amount: Decimal, rate_eff: Decimal, twd: int, quote: Quote|None, fee_on)`.

Add form (called right after `_country_location_selectors("add")`, line 207):

| Widget | Key | Why this key |
|---|---|---|
| 幣別 selectbox, options `[COUNTRY_CURRENCY.get(country,"TWD")] + others` (TWD always present) | `add_currency_{country}` | mirrors `add_location_{country}`: switching 新加坡→馬來西亞 re-creates the widget with MYR; persists across saves within a trip |
| 原幣金額 number_input `min_value=0.0, step=CURRENCY_META[c].step (float), format per decimals, value=None` (G12) | `add_fx_amount_{gen}` | cleared by the post-save `add_form_gen += 1`; otherwise the previous amount survives and double-logs |
| 匯率 number_input `value=quote.rate, format="%.6f"` | `add_fx_rate_{currency}_{quote.date}` | A's trick: persists a manual override during the day, re-seeds from a fresh quote tomorrow (keyed number_input ignores a new `value=` — key-as-main-identity, `number_input.py:504`) |
| 信用卡結匯 +1.5% toggle | `add_fx_fee_{country}` | G15: a new trip (new country) starts with the toggle off; never inherited |
| ↻ 重新取得匯率 button | `add_fx_refresh` | `on_click` → `fx.invalidate(currency, date)` + `del session_state[rate_key]` |

Fee handling (fixes C's session_state re-seed trick): the 匯率 widget always shows the mid-market quote; `rate_eff = q6(rate_widget × (1.015 if fee_on else 1))` is computed arithmetically; the caption states 「含手續費」 and shows `rate_eff`. The stored 匯率 is `rate_eff`. No widget is ever re-seeded from session_state.

Inside the form: `if fx is None: amount = st.number_input(... key=f"add_amount_{gen}")  # unchanged` else `st.info(...)`; `amount = fx.twd`. The keyed `add_amount_{gen}` is simply not instantiated in FX mode (its stale state is never read).

Submit branch (lines 289-340): `amount` is already an int in both modes → validation (300) adds 「請輸入原幣金額」/「匯率無效」; duplicate signature (310) becomes `(date, account, description, amount, currency, orig_amount)` (graft B); `expense_data.update(currency=..., orig_amount=..., fx_rate=...)` (blank strings for TWD rows); flash shows both amounts. After `add_expense` returns True, read `api.last_write_warnings` and surface 「工作表尚未有 幣別/原幣金額/匯率 欄位，此筆只儲存了台幣金額」 if the FX fields were dropped (§2.5).

Pre-submit hint (G5 — no per-rerun Sheets call): `_load_from_api`/`_load_from_csv` stamp `df.attrs["fx_headers"] = bool` from the raw header row they already read; the add form shows a one-line `st.caption("⚠️ 工作表尚未新增幣別欄位")` only when `attrs.get("fx_headers") is False` and a non-TWD currency is active. `has_fx_columns()` therefore costs zero API calls, refreshes with the 60 s data cache, and is `None`/unknown for a legacy `last_good_df` (no warning, the post-write check still fires).

### 2.3 Rate source, fallback chain, caching (`fx.py`, new)

Chain, first success wins, `requests` timeout 3 s each (verified endpoints, 2026-09-08):

1. Frankfurter v2 `GET https://api.frankfurter.dev/v2/rates?base={CCY}&quotes=TWD[&date=YYYY-MM-DD]` (has TWD, dated lookups, no key, no attribution).
2. open.er-api `GET https://open.er-api.com/v6/latest/{CCY}` → `rates.TWD`; skip if `time_eol_unix != 0`; today only; attribution link required in the caption when used.
3. fawazahmed0 `https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date|latest}/v1/currencies/{ccy}.min.json`, then mirror `https://{date|latest}.currency-api.pages.dev/...`.
4. **上次使用** (graft from design 2): most recent row in the loaded df with that currency → its `fx_rate`, labelled 「🔁 上次使用 MM/DD」. Works with no signal at all.
5. `config.FX_FALLBACK_RATES` (TWD per unit, stamped `FX_FALLBACK_DATE = "2026-09-08"`: USD 31.54, SGD 24.91, MYR 7.79, JPY 0.2035, KRW 0.02345, AUD 22.77, CAD 22.84, EUR 36.66) → state `static`, caption 「⚠️ 離線匯率 2026-09-08，請確認」.

`Quote = (currency, rate: Decimal, as_of: date, source, state ∈ {live, cached, stale, last_used, static}, fetched_at)`.

Caching (G9, explicit):
```python
@st.cache_resource            # ONE holder object; never memoises a None
def _fx_store() -> dict:      # {"quotes": {}, "last_good": {}, "neg": {}}
    return {"quotes": {}, "last_good": {}, "neg": {}}

def get_quote(ccy, on_date, df=None) -> Quote:
    s = _fx_store(); k = (ccy, on_date.isoformat())
    q = s["quotes"].get(k)
    if q and now - q.fetched_at < 12h: return q            # state cached
    if k in s["neg"] and now - s["neg"][k] < 10min:         # negative cache
        return s["last_good"].get(ccy, state="stale") or last_used(df) or static()
    q = _run_chain(ccy, on_date)                            # sources 1-3
    if q: s["quotes"][k] = q; s["last_good"][ccy] = q; s["neg"].pop(k, None); return q
    s["neg"][k] = now
    return s["last_good"].get(ccy)→stale or last_used(df) or static()

def invalidate(ccy, on_date): s["quotes"].pop(k, None); s["neg"].pop(k, None)
```
- `st.cache_resource`, not `st.cache_data`: the eight `st.cache_data.clear()` sites (input_forms 335/620/641, sheets_api 588/630/661/744/756) would flush an FX cache after every save and could trip er-api's 429.
- Worst-case first fetch = 4 endpoints × 3 s = **12 s**, shown behind `st.spinner`; the negative cache guarantees it is paid at most once per 10 min.
- Fetch is triggered only inside `_fx_block` when the active currency ≠ TWD — never at import, never from 總覽, never when 國家 = 台灣.
- Timestamps via `helpers.now_local()` (Cloud runs UTC).
- Community Cloud sleep wipes the store; first foreign entry after wake pays one fetch.

Date rule: the add form quotes `today_local()` because 日期 is inside the form (G10, documented in §2.7); the edit form quotes the row's 日期.

### 2.4 Data model, migration, back-compat

Sheet (GID 453361449): A..I unchanged; `EXPECTED_HEADERS` stays at the 9 names; the write refusal is untouched. Three **optional** header cells are added, by name, in the first empty header cells after the last used column (G11 — not hard-coded to J1:L1):

| Header | internal | Type | Blank means |
|---|---|---|---|
| 幣別 | `currency` | ISO-4217 upper (SGD, MYR, JPY, KRW, AUD, CAD, USD, EUR, …) | TWD-native |
| 原幣金額 | `orig_amount` | decimal, `CURRENCY_META[c].decimals` (0 for JPY/KRW, else 2) | — |
| 匯率 | `fx_rate` | TWD per 1 unit, **6 dp for all currencies** (G3), the effective rate actually used (fee folded in) | — |

Invariant (write-time, audited on read): `currency != ""` ⇒ `abs(金額 − to_twd(原幣金額, 匯率)) ≤ 1`, tolerance applied to **all** rows (G3); `currency == ""` ⇒ K, L blank. `金額 = to_twd(orig, rate_stored)` is always computed from the rate **after** rounding to 6 dp, never from an unrounded product. Check: JPY 200,000 reconciled to 41,013 → rate 0.205065 → 200,000 × 0.205065 = 41,013 exactly; KRW 500,000 error bound 500,000 × 5e-7 = 0.25 < 1.

`helpers.to_twd` (G2):
```python
def to_twd(orig, rate, orig_dp) -> int:
    o = Decimal(str(orig)).quantize(Decimal(1).scaleb(-orig_dp))
    r = Decimal(str(rate)).quantize(Decimal("0.000001"))
    return int((o * r).quantize(Decimal(1), rounding=ROUND_HALF_UP))
# Decimal(12.5)*Decimal(23.4) = 292.4999… → wrong; Decimal("12.5")*Decimal("23.4") = 292.5 → 293 (verified)
```

Existing 2,065 rows: zero rewrite; blank J..L read as `currency=""`, `orig_amount=NaN`, `fx_rate=NaN`, treated as TWD-native everywhere (totals unchanged to the cent). Google-Form-appended rows (if any) also arrive blank = TWD.

Migration `scripts/migrate_add_currency_columns.py` (graft B, corrected per G11): opens `sheet_id`/`worksheet_gid` from secrets or CLI flags; asserts the 9 required names are all present in row 1 (any order); if the three FX names are already present → prints "already migrated" and exits 0; else finds the first three consecutive empty header cells after the last non-empty header and writes them; refuses if the target cells are non-empty; `--dry-run` prints the target cell letters; prints resulting header row. No data row touched. Rollback = clear the three FX header cells (found by name); code tolerates absence.

Rehearsal (G1): `WORKSHEET_GID` is a hard-coded constant used at `sheets_api.py:213/325`, so step 2 adds `_resolve_worksheet_gid()` = `_secret("app","worksheet_gid", WORKSHEET_GID)` and a commented `worksheet_gid` line in `streamlit_secrets.template.toml`. Rehearsal = File → Make a copy of the whole spreadsheet (copies get NEW GIDs — look the tab's gid up in the copy's URL), point local `secrets.toml` at the copy's `sheet_id` + `worksheet_gid`, run the migration script and the app against the copy.

Loader (`_process_data`): `COLUMN_MAPPING += {幣別, 原幣金額, 匯率}` (the latin-1 round-trip in `_load_from_csv` finds proper-Chinese entries, no mojibake spellings needed); `TEXT_FIELDS += currency` (upper-cased, `"TWD"` normalised to `""`); `orig_amount`/`fx_rate` parsed with `pd.to_numeric(str.replace(",",""), errors="coerce")` — NOT `parse_amount` (it strips `NT$`/`TWD` tokens and int-coerces); `EXPECTED_COLUMNS += 3` so `_empty_df` and the session fallback frame match; `df.attrs["fx_headers"]` set as in §2.2. Every consumer guards `"currency" in df.columns` for a `last_good_df` captured before deploy (G15).

Writer: `OPTIONAL_HEADERS = ["幣別","原幣金額","匯率"]`; `_header_map` maps them when present (refusal logic unchanged); `_cell_value` formats `orig_amount` with currency decimals and `fx_rate` as `"%.6f"` trimmed (never via `_sheet_amount_value`'s int coercion), `currency` via `_clean_text().upper()`; `add_expense` records dropped FX fields in `self.last_write_warnings`. `update_expense` unchanged in shape.

CSV fallback (read-only mode): pandas reads the extra columns as str; blanks → `""`; converted rows display fine; saving is impossible there regardless (unchanged).

### 2.5 Edit form (編輯 tab)

- Snapshot `edit_orig_g{gen}_{row}` gains `currency/orig_amount/fx_rate`.
- `_record_label` appends ` (SGD 12.50)` for converted rows.
- **Default 幣別 = stored currency (`""` → TWD), regardless of 國家** (G4). The FX card is rendered outside the form only when the stored currency is non-blank OR the user ticks a small checkbox `💱 換算為外幣` (key `{kp}_fx_optin_{row}`) placed under 地點. Legacy 日本/澳洲/新加坡 rows therefore open exactly as today (金額 widget present, no FX keys). `COUNTRY_CURRENCY.get(country, "TWD")` everywhere — blank/legacy 國家 values inserted by `_options_with` cannot raise.
- Card keys: `{kp}_currency_{row}`, `{kp}_fx_amount_{row}`, `{kp}_fx_rate_{row}_{ccy}`, `{kp}_fx_fee_{row}`, `{kp}_keep_twd_{row}`, `{kp}_stmt_{row}` — all carry `kp` and `sheet_row` so `_bump_edit_generation` invalidates them and a re-used row number never inherits a stale rate. Quote date = row 日期.
- Extra outside-form fields when the card is shown:
  - `保留原台幣金額（反推匯率）` checkbox (graft B), default **ON** when the row already has 金額 and no stored currency (the back-fill case): 金額 stays, `fx_rate = q6(金額 / orig_amount)`. Totals never move.
  - `💳 帳單金額 (TWD)` number_input (design C reconciliation): when given, `金額 = stmt`, `fx_rate = q6(stmt / orig_amount)`; one field, one tap.
- In-form 金額: hidden (caption) while the card is active; editable as today otherwise.
- On 更新, rules in order: (i) 帳單金額 given → as above; (ii) 保留原台幣金額 on → as above; (iii) else 金額 = `to_twd(orig, rate_eff)`; (iv) 幣別 set to TWD → all three FX cells written as `""`. `updated_data` **always carries the three FX keys explicitly** (explicit blanks, not omit-if-unchanged — graft B) whenever the card was shown, so a stale (orig, rate) can never sit beside a new 金額; when the card was not shown the three keys are omitted and `update_expense` preserves them.
- Delete path unchanged.

### 2.6 How 總覽 treats converted rows

- All sums/charts use `amount` (TWD) — no arithmetic change.
- Transaction lists: `原幣` shown as a sub-label / column (`SGD 12.50`) only when the slice contains at least one converted row.
- Hero/stat strip: when the period's converted rows share one currency, the ✈️ 旅行 tile shows `NT$18,240 (SGD 782)`; with several currencies, one chip line per currency `🌏 SGD 187.50 ≈ NT$4,680 · MYR 210 ≈ NT$1,636`.
- 🧹 資料檢查 expander: 「已換算外幣 N 筆」 and 「換算不一致 M 筆」 (|金額 − to_twd(orig, rate)| > 1, all converted rows) with the row names so they can be fixed in 編輯.
- Rows without 幣別 on foreign trips are counted as 「未標幣別 N 筆」 in the trip view, so partial SGD totals are labelled as partial.

### 2.7 Edge cases

| Case | Behaviour |
|---|---|
| FX API unreachable (airport Wi-Fi, roaming) | chain → stale last-good (dated) → 上次使用 from df → static table; caption states the state; save always possible. Negative cache: no repeated 12 s stalls. Streamlit itself still needs the server — "offline" means FX-API-offline only. |
| Stale rate | never shown as fresh: state + as-of date in the caption; `(currency, quote_date)` key re-seeds the 匯率 widget the next day automatically; ↻ forces a refetch. |
| Rounding | `to_twd` = Decimal(str()) half-up to integer TWD; rate stored at 6 dp; ±1 tolerance in the audit. JPY/KRW amounts have 0 decimals (step 1). |
| Refunds / negative amounts | today 金額 has `min_value=0`; 原幣金額 keeps `min_value=0.0`. Refunds stay out of scope (unchanged behaviour); noted in §6 Q5. |
| TWD purchase abroad | 幣別 → TWD in the card (persists per country until changed); plain TWD row. |
| Editing a converted row | §2.5 rules; 幣別 defaults to stored value; hand-typing a new 金額 is only possible after setting 幣別 → TWD (which blanks the FX cells) or via 帳單金額 (which re-derives the rate) — 金額 and (orig, rate) can never disagree. |
| Manual rate override | edit 匯率 in 進階; stored as used; `(currency, quote_date)` key keeps it for the day. |
| Back-dated add | add form quotes today's rate even if 日期 is set to yesterday inside the form (日期 is unreachable before submit); the edit form quotes the row date, so a later edit may suggest a different rate. Documented limitation; see §6 Q3. |
| Un-migrated sheet | TWD row saved; FX fields dropped; pre-submit caption + post-write warning. |
| Two different SGD amounts rounding to the same TWD within 120 s | duplicate signature now includes `orig_amount` → not refused. |
| Card-fee mismatch with statement | +1.5% toggle at entry; exact figure via 帳單金額 later. |
| Someone renames an FX header by hand in Sheets | code degrades to 9-column behaviour; warning on next foreign save; DEPLOYMENT.md lists the three names. |

---

## 3. 總覽 refinement

### 3.1 Information hierarchy
1. Period (one control) → 2. Hero: total, delta vs a named comparison window, sparkline → 3. Stat strip: 今天 / per-account / 日常·旅行 → 4. Top-3 categories as bars → 5. 最近 5 筆 → 6. progressive disclosure (expanders): 本期全部交易, 趨勢, 帳戶與類型, 篩選, 資料檢查.
Every fact is stated once. Record counts and 平均單筆 leave the first screen (count survives as `3 筆` in the 今天 tile and list footers).

### 3.2 Screen-by-screen at 390 px

Chrome (all tabs): `.main-header` shrunk to one 36 px line; the green API banner is removed when healthy (🟢 dot + text in the sidebar caption); the amber 唯讀模式 banner stays. `st.tabs([...], key="main_tab", default=session default)` so the chosen tab survives reruns (G14; it does not survive a full reload — see §6 Q2 for putting 總覽 first).

Screen 1 (y ≈ 100–770; the 3-second answer needs 1 tap, 0 scrolls; the measured height is ~770 px, so the 5-row list is the first thing below the fold on a 664 px viewport — acceptable):
- Row 1 `st.segmented_control(label_visibility="collapsed", options=["今天","本週","本月","本年","更多…"], key="ov_seg", default="本月")`. `更多…` opens `st.popover("更多期間")`: `st.pills` 上月 / 最近7天 / 最近30天 / 全部; `自訂範圍` two `date_input`s defaulting to first-of-month..today with the existing end<start validation kept (G8); a trip list (one row per detected trip with a `查看` button — graft 3). **Period resolution (fixes the state trap):** one canonical `st.session_state["ov_period"] = {label, start, end, country}`; the segmented control's `on_change` writes it and clears the popover keys; every popover control's `on_change` writes it and sets `session_state["ov_seg"] = "更多…"` (legal inside a callback). No priority order exists.
- Row 2 hero: `st.metric(label="本月支出 · 09/01–09/08", value="NT$74,150", delta="比上月同期 −12% (−NT$10,090)", delta_color="inverse", border=True, chart_data=daily totals reindexed over the full period incl. zero days, delta_description=COMPARISON_LABEL text)`. Caption: 「日均 NT$9,269 · 照此步調月底約 NT$278,000 · 上月全月 NT$212,300」. `COMPARISON_LABEL` (graft 3): 今天→昨天, 本週→上週同期 (Mon..same weekday), 本月→上月同期, 上月→前一個月, 本年→去年同期, 最近7天/30天→前 N 天, 自訂→前 N 天, 旅行→無比較. Empty comparison → delta `None` + 「無前期資料」 (never dropped silently).
- Row 3 stat strip: static HTML 2-col grid (`st.markdown(unsafe_allow_html=True)`; HTML only for **static** tiles — G6) `[今天 NT$620 · 3 筆] [菇菇 NT$41,200 / 過兒 NT$32,950]`; a third tile `[✈️ 旅行 NT$18,240 · SGD 782] [📅 日常 NT$55,910]` when the period has 旅行 rows. Colours via Streamlit CSS variables `var(--text-color)`, `var(--secondary-background-color)`, `var(--primary-color)` (G12 — not `prefers-color-scheme`).
- Active-trip badge (replaces design 1's auto-default — G7): when `detect_trips` finds a trip with `end ≥ today−3`, a line 「🇸🇬 正在旅行中 · 新加坡 09/05– NT$18,240」 + `查看` button under the hero; tie-break when several are active = latest end date, then latest start. Default period stays 本月.
- Row 4 top-3 categories: three static HTML bar rows `🍽️ 飲食 NT$21,300 ▇▇▇▇▇ 29%` + 「其他 13 類 NT$…」. No pie.
- Row 5 最近 5 筆: `st.dataframe(height="auto", row_height=34, hide_index=True)`, columns 日期 (MM/DD) | 名稱 | 金額 (NumberColumn `NT$%d`, right-aligned); converted rows show `咖啡 · SGD 12.50`; toolbar hidden via CSS `[data-testid="stElementToolbar"]{display:none}` under a ≤ 640 px media query.
- Filter echo: `st.badge("篩選: 菇菇 · 飲食")` + a small `清除` `st.button` (G12 — badge is static).

Below (all collapsed expanders, one tap each):
- 📋 本期全部交易 (N 筆): stable sort `(date desc, sheet_row desc, kind="mergesort")`, columns 日期 | 分類 | 名稱 | 金額 | 帳戶 | 原幣(conditional), 備註 as `column_config` help; `height=min(n,12)*34+38` (int — `"auto"` caps at 10 rows); footer 「本期 N 筆 · 最大一筆 NT$18,900 機票 (09/02)」 (graft 3), never a 15-row total.
- 📈 趨勢: period ≤ 45 days → cumulative daily line 本期 vs 比較期 on a categorical day-of-period axis (graft 3; immune to the single-point millisecond-axis bug); > 45 days → monthly bars, `fig.update_xaxes(type="category")`, current month marked 進行中, y from 0; plus a 月份 | 支出 | 筆數 table for 本年/全部. All charts `config={"staticPlot": True, "displayModeBar": False}`, height ≤ 280.
- 👤 帳戶與類型: account × category table + 日常/旅行 split. Weekday-mean chart, pie, ranking table and account bar chart are deleted.
- 🔍 篩選: `st.pills` 帳戶 (multi), `st.pills` 類型 (📅 日常 / ✈️ 旅行 — the biggest unsurfaced dimension), `st.multiselect` 分類 (17 options do not fit as pills) and 國家; **no 全部 sentinel** — empty = no filter; `_prune_filter_state` kept.
- 🧹 資料檢查 (renamed from 資料品質資訊, computed on the period, states its scope): unparseable/zero-amount rows listed by 日期+名稱; 已換算外幣 / 換算不一致 / 未標幣別 counts.

Empty period: one `st.info("本月尚無支出 — 試試 上月 或 全部")` with two buttons that set `ov_period`; nothing else renders.

### 3.3 Controls removed / merged / moved

| Today | Change |
|---|---|
| `st.title 📊 支出總覽`, h3 時間範圍選擇, six quick buttons, 9-option selectbox, `st.info` period echo, `st.success` N/M 筆記錄 line, two-line 期間統計 h3, 統計期間 caption, detached 與前期比較 caption | removed; replaced by segmented control + hero (period and comparison stated once) |
| Four stacked `st.metric` (總支出/交易次數/平均單筆/日均) | 總支出 → hero; 日均 → hero caption; 交易次數 → tile/footers; 平均單筆 removed |
| 進階篩選 expander with 全部 sentinels | 🔍 篩選 expander with pills/multiselect, empty = all |
| 自訂範圍 defaulting to full history | defaults to current month; moved into the popover |
| 資料品質資訊 (full-df) between metrics and list | 🧹 資料檢查 at the bottom, period-scoped |
| 最近交易 fixed 400 px, 15 rows, 5 emoji columns | 5-row auto-height list + full-period list in expander |
| pie + 分類排行榜 + monthly line + weekday mean + account bar | top-3 bars + 趨勢/帳戶 expanders |
| always-on green API banner | sidebar dot |
| dead CSS `.stButton height:3rem`, `.stDeployButton` | removed; toolbar-hide rule added |

Category canonicalisation (`📱通信` vs `📱 通信`): applied by `app.canonical_category()` at display/grouping time only — never in `_process_data` — so edit snapshots and the sheet keep raw values (graft 3, addresses judge deduction).

`detect_trips(df)` (`overview.py`): rows with `type_1 == ✈️ 旅行` and `country not in ("", "台灣")` grouped by country, split on gaps > `TRIP_GAP_DAYS = 3`; 旅行 rows with 國家 = 台灣 (flights/hotels bought at home) are attached as 「行前」 to the next trip of any country starting within 180 days, else listed as 「行前 · 尚未出發」 — never a "台灣 trip" (G13).

### 3.4 What stays for desktop
Same page; at ≥ 640 px the HTML grid becomes 4 tiles per row, the top-3 bars sit beside the hero via `st.columns` (which only stacks below 640 px), the transaction expander opens by default, and the 趨勢 chart height is 360. No desktop-only widgets; the removed charts are not retained anywhere (their information lives in the account × category table and monthly table).

---

## 4. File-by-file change list

**`config.py`**
- Add `COUNTRY_CURRENCY = {台灣:TWD, 日本:JPY, 澳洲:AUD, 加拿大:CAD, 韓國:KRW, 新加坡:SGD, 馬來西亞:MYR}` (used via `.get(..., "TWD")`), `CURRENCY_OPTIONS`, `CURRENCY_META = {code: (decimals, step)}` (JPY/KRW 0/1.0; others 2/0.01), `RATE_DECIMALS = 6`, `CARD_FX_FEE = Decimal("0.015")`, `FX_FALLBACK_RATES`, `FX_FALLBACK_DATE`, `FX_TIMEOUT_S = 3`, `FX_TTL_H = 12`, `FX_NEG_CACHE_MIN = 10`, `FX_ENDPOINTS`.
- `COLUMN_MAPPING += {'幣別':'currency','原幣金額':'orig_amount','匯率':'fx_rate'}`.
- Dashboard: `OVERVIEW_PERIODS`, `COMPARISON_LABEL`, `CATEGORY_ALIASES`, `COUNTRY_FLAG`, `TRIP_GAP_DAYS = 3`, `TRIP_PREBOOK_WINDOW_DAYS = 180`, `TRIP_ACTIVE_GRACE_DAYS = 3`.

**`helpers.py`**
- Add `now_local()`, `to_twd(orig, rate, orig_dp) -> int` (Decimal(str) half-up), `q6(x) -> Decimal`, `fmt_orig(currency, value)`, `fmt_twd(n)`, `fmt_pct(x)`, `week_bounds(d)`. `parse_amount` untouched.

**`fx.py`** (new)
- `Quote` dataclass; `_fetch_frankfurter`, `_fetch_erapi`, `_fetch_fawaz` (strict JSON validation, timeout); `_fx_store()` under `@st.cache_resource`; `get_quote(currency, on_date, df=None)`; `last_used_rate(df, currency)`; `invalidate(currency, on_date)`; `freshness_caption(quote)` incl. the er-api attribution link; `effective_rate(quote_rate, fee_on)`.

**`sheets_api.py`**
- `_resolve_worksheet_gid()`; replace the three `WORKSHEET_GID` uses (213, 325, 679) and the error strings.
- `OPTIONAL_HEADERS`; `TEXT_FIELDS += currency`; `EXPECTED_COLUMNS += 3`; `_header_map` maps optional headers when present; `_cell_value` formats `orig_amount`/`fx_rate`/`currency`; `_process_data` parses the two numerics with `to_numeric`, normalises currency, sets `df.attrs["fx_headers"]` (from `_load_from_api`/`_load_from_csv`); `add_expense` fills `self.last_write_warnings`; `has_fx_columns(df)` reads `df.attrs` only; `refresh_data`/`reconnect` unchanged apart from GID resolution.

**`input_forms.py`**
- `FxState`, `FxStored`, `_fx_block(...)`; `expense_input_form`: call after line 207, conditional in-form 金額, submit branch changes (§2.2); `edit_expense_form`: snapshot +3 fields, opt-in checkbox, `_fx_block` with stored values / row date / 保留原台幣金額 / 帳單金額, update rules (i)–(iv), explicit FX blanks; `_record_label` suffix; `COUNTRY_CURRENCY.get`.

**`app.py`**
- `main_dashboard()` rewritten top-down: `period_control()` (segmented control + popover + callbacks writing `ov_period`), `show_hero()`, `show_active_trip_badge()`, `show_stat_strip()`, `show_top_categories()`, `show_recent_list()`, `show_period_transactions()`, `show_trend_expander()`, `show_accounts_expander()`, `filter_expander()` + `filter_badge()`, `show_data_check_expander()`, `show_empty_period()`; `get_comparison_period()` gains 今天/本週 branches and returns the label; `apply_additional_filters(df, filters: dict)` with type_1/country and no sentinel; `canonical_category()`; `period_summary()` under `@st.cache_data(ttl=60)` keyed on (period tuple, filters tuple); `show_api_status()` → sidebar dot; `st.tabs(key="main_tab")`; CSS block replaced.

**`overview.py`** (new) — pure functions: `period_summary(df, start, end, filters)`, `detect_trips(df, today)`, `active_trip(trips, today)`, `daily_series(df, start, end)`, `monthly_series(df)`. No Streamlit import → unit-testable.

**`scripts/migrate_add_currency_columns.py`** (new) — as §2.4.

**`requirements.txt`** — `streamlit>=1.55,<2` (segmented_control, pills, popover, badge, metric border/chart_data/delta_description, dataframe row_height, tabs key/default); `requests` already present. **`requirements-dev.txt`** (new, G8): `pytest`, `pytest-mock`.

**`streamlit_secrets.template.toml`** — add commented `worksheet_gid = 453361449` under `[app]`.

**`tests/`** (new): `conftest.py` (stubs below), `test_helpers_fx.py`, `test_fx.py`, `test_sheets_fx.py`, `test_overview.py`, `test_forms_apptest.py`, `test_dashboard_apptest.py`, `fixtures/` (frankfurter.json, erapi.json, fawaz.json, snapshot CSV = `new_to_fill.csv` with dates shifted to today).

**`DEPLOYMENT.md` / `README.md`** — migration runbook (copy-sheet rehearsal, GID lookup, deploy order, rollback), rate sources + er-api attribution note, how to refresh `FX_FALLBACK_RATES`, back-dated-entry limitation, the three FX header names.

`auth.py` — untouched (only monkeypatched in tests).

---

## 5. Implementation order (each step deployable alone)

Test tooling common to all steps (G8): `expense_env/bin/python -m pytest tests/`; `tests/conftest.py` provides `fake_api` (stub `SheetsAPI` with an in-memory worksheet: `row_values`, `append_row`, `update`, `delete_rows`, `get_all_values`), `monkeypatch` of `input_forms.get_sheets_api`, `input_forms.get_current_user` (auth.py is only patched, never edited), `sheets_api.load_expense_data` → fixture df, and `requests.get` → fixture responses or `raise ConnectionError`. AppTest via `streamlit.testing.v1.AppTest.from_function(lambda: expense_input_form())` etc. Headless Chrome checks reuse the existing stub harness under `/tmp/claude-1001/.../scratchpad/run/` (390×844, touch emulation). Rollback for every step = `git revert` of that step's commit; the sheet is only touched in step 2b.

| Step | Ships | Tests | Rollback |
|---|---|---|---|
| **0. Tooling** | `requirements-dev.txt`, `tests/conftest.py`, fixtures, `pytest` green on an empty suite; pin `streamlit>=1.55,<2`; verify `auth.py` cookie login still works on the pinned version (manual). | `pytest -q` runs; AppTest smoke renders `main()` with stubs. | revert pin. |
| **1. Pure FX helpers** (`helpers.py`, `config.py`, `fx.py`, no UI) | `to_twd`, `q6`, `fmt_orig`, `COUNTRY_CURRENCY`, `fx.get_quote` + store. | Unit: `to_twd(12.5, 23.4)==293`, `to_twd(0.1×3-style floats)`, JPY 200,000 @ 0.205065 == 41,013, KRW 500,000 @ 0.02345 == 11,725, half-up at every .5 boundary asserting `Decimal(str())` (G2); `fx`: chain order, per-source timeout/5xx/malformed JSON fallthrough, er-api `time_eol_unix≠0` skipped, stale-while-error, 上次使用 tier from df, static tier state, **failed chain is not memoised** (second call after fixing `requests` returns live — G9), negative cache expiry, `invalidate` evicts one key, store is `cache_resource` (survives `st.cache_data.clear()`). | revert; no user-visible change. |
| **2a. Loader/writer tolerate FX columns** (`sheets_api.py`, `config.py`, secrets template) | `OPTIONAL_HEADERS`, `_header_map`, `_cell_value`, `_process_data` (+`attrs`), `_resolve_worksheet_gid`, `last_write_warnings`. Deployed BEFORE the sheet changes; behaviour on the 9-column sheet is identical. | Unit: `_process_data` on the 1,577-row snapshot → totals identical to the cent, `currency==""` everywhere, `attrs["fx_headers"] is False`; 12-column frame with blanks/`'12.5'`/`'sgd'`; CSV mojibake path; `_header_map` with 9 / 12 headers in shuffled order; 9-header refusal intact; `_cell_value` rate `0.205065` written as `"0.205065"` not int; `update_expense` explicit `""` blanks; `add_expense` with FX payload on 9-header sheet → row written, warning recorded; `row_values(1)` called once per write and never from a dashboard render (G5); `_resolve_worksheet_gid` honours the secret. | revert; sheet untouched. |
| **2b. Migration** (script + runbook) | Rehearse on a full spreadsheet copy with secrets pointed at the copy's `sheet_id`/`worksheet_gid` (G1): `--dry-run`, run, app add/edit/delete one SGD row (using step-3 build locally), verify rows 2..N unchanged; then run against the live sheet; sidebar 🔄 重新整理. | Script unit tests on a fake worksheet: 9 names present in any order → writes into first empty cells and prints letters; already migrated → no-op; non-empty target → refuses; missing required name → refuses (G11). | clear the three FX header cells by name; code from 2a keeps working. |
| **3. Add-form FX card** (`input_forms.py` add path) | `_fx_block` for 新增, conditional 金額, submit changes, flash, warnings. | AppTest: 國家=新加坡 → 幣別 SGD, type 12.5 → in-form 金額 absent, payload `amount==313`/`currency=="SGD"`; 國家=台灣 → no FX keys, 金額 present; after save `add_fx_amount_{gen}` gone, `add_fx_rate_SGD_{date}` kept, `add_fx_fee_新加坡` off for 馬來西亞; fee on → stored rate = q6(mid×1.015) and 金額 recomputed from the stored rate; two different SGD amounts rounding to same TWD within 120 s both accepted; identical entry refused; `requests` raising → static caption, save succeeds; **rendering 總覽 and a 台灣 entry makes zero HTTP calls** (`requests.get` monkeypatched to raise — G8). Headless Chrome 390 px: card + metric visible without scroll under 地點. Manual phone (both accounts, iOS Safari + Android Chrome). | revert; rows already written keep valid FX cells. |
| **4. Edit-form FX** (`input_forms.py` edit path) | opt-in checkbox, stored-currency default, 保留原台幣金額, 帳單金額, rules (i)–(iv), explicit blanks, `_record_label`. | AppTest: legacy 新加坡 row (blank currency) opens with 金額 widget present and no FX keys (G4); row with blank 國家 does not raise; converted row → card prefilled, 金額 hidden; 帳單金額 41,013 on JPY 200,000 → rate 0.205065, invariant within ±1 (G3); back-fill with 保留原台幣金額 → 金額 unchanged, rate derived; 幣別→TWD → three `""` written; untouched card → FX keys omitted from `updated_data`. | revert. |
| **5. 總覽 minimal FX display** (`app.py`) | 原幣 column in 最近交易 when present; 已換算外幣/換算不一致 counts in 資料品質資訊. Independent of the redesign. | Unit on snapshot + 3 injected converted rows; `last_good_df` without `currency` column renders without KeyError (G15). | revert. |
| **6. 總覽 skeleton** (`app.py`, `overview.py`) | period control + callbacks, hero with `COMPARISON_LABEL`, stat strip, top-3 bars, 5-row list, empty state, chrome changes, `st.tabs(key)`; old sections kept temporarily below a divider. | Unit: `get_comparison_period` for all presets incl. 本週 on a Tuesday, 本月 on the 31st, 今天 vs 昨天; `period_summary`; delta `None` + 無前期資料 when comparison empty; popover custom range end<start rejected (G8); segmented tap after a popover choice wins and vice-versa (state trap); `period_summary` cache key includes filters. AppTest: default period 本月 on 2026-09-08 with active trips (G7). Headless Chrome: first metric y < 400, no horizontal scroll, page height ≤ 2,300 px. | revert. |
| **7. 總覽 expanders + deletions** | 本期全部交易, 趨勢, 帳戶與類型, 篩選 pills (no sentinel), 資料檢查; delete pie/ranking/weekday/account chart/old controls; static Plotly config. | Unit: stable sort (same-day rows by sheet_row desc); filter with empty lists = no filter; trend figure x-axis `category` for single-month; cumulative series length = period days; `canonical_category` merges `📱通信`, raw column untouched. Headless Chrome: charts do not draw zoom boxes (config check via DOM), toolbar hidden ≤ 640 px, dark/light theme screenshots. | revert to step 6 build. |
| **8. Trips** (`overview.detect_trips`, badge, popover trip list, 查看) | trip detection, active-trip badge with tie-break, 查看 sets `ov_period` + 國家 filter, per-currency chips, 未標幣別 count. | Golden test on the snapshot: 澳洲 2026-01-14..30 with 2025-12-06 flight as 行前, 日本 06-13..20, 加拿大 upcoming, 新加坡 09-05..07 then 馬來西亞 09-08 as two trips; a 旅行+台灣 row never forms a 台灣 trip (G13); gap 3 vs 4 days; tie-break latest end date. | revert; nothing stored. |
| **9. Docs & cleanup** | README/DEPLOYMENT, remove dead code paths, refresh `FX_FALLBACK_RATES`. | full suite green; manual phone pass of §2.1 and §3.2 flows by both users. | n/a |

Estimated effort: converter (steps 0–5) ≈ 4.5 days; 總覽 (6–9) ≈ 5.5 days.

---

## 6. Risks & open questions for the user

Open questions (each changes the design):

1. **Q1 — Sheet header names.** The task forbade touching the sheet, so the live header row was never read. If it already has more than 9 used columns (e.g. Google-Form timestamp), the script writes the FX headers after the last used column; confirm that is acceptable and that no hidden columns exist.
2. **Q2 — Tab order.** `st.tabs(key)` keeps the tab across reruns but not across reloads; making 總覽 the first tab would give 0 taps for reading and 1 tap for adding. Default in this plan: keep 新增 first (the in-shop path wins).
3. **Q3 — Back-dated entries.** Keep 日期 inside the form (rate = today's, documented) or move 日期 outside the form (one more rerun on change, but the quote follows the chosen date). Default: keep inside.
4. **Q4 — Reconciliation/provenance column.** Without a 4th column (匯率來源) the app cannot count 「未對帳」 rows or flag rows saved with a static rate after the fact. Default: 3 columns; add 匯率來源 in v2 if the family reconciles statements regularly.
5. **Q5 — Refunds.** Today 金額 cannot be negative; foreign refunds would need `min_value` relaxed in both amount widgets and a sign-aware duplicate signature. Default: out of scope.
6. **Q6 — 本月 semantics.** This plan keeps 本月 = everything (旅行 included) with a 日常/旅行 tile and a 類型 filter; design 2's "exclude 旅行 from 本月 by default" is rejected unless the family wants monthly figures to be household-only.
7. **Q7 — Frankfurter blend vs bank rate.** Mid-market blend + optional 1.5% is the default; if the family wants Bank of Taiwan 即期賣出 specifically, it must be typed manually (BOT blocks datacenter IPs).

Risks (design already mitigates):
- Manual migration typo → silent 9-column degradation; mitigated by the script (writes by name), pre-submit caption, post-write warning, rehearsal on a copy.
- Streamlit DOM/CSS churn for the HTML tiles and toolbar-hide rule; mitigated by pinning `streamlit>=1.55,<2`, CSS variables, headless screenshots in both themes.
- Free FX sources are one-maintainer or attribution-bound; mitigated by the 5-tier chain, visible state, editable rate.
- Community Cloud sleep → one 12 s worst-case fetch after wake; mitigated by spinner, negative cache, fetch on the 國家 change rerun.
- Trip heuristics can merge/split; the badge and popover show date ranges and 自訂範圍 remains.
- Every outside-form change is a full rerun of all three tabs (unchanged architecture); `period_summary`/data/FX caches bound the cost.

---

### Critic findings → where addressed

| Gap | Where |
|---|---|
| G1 GID override / rehearsal | §2.4 rehearsal, §4 `sheets_api.py` + secrets template, step 2a/2b |
| G2 Decimal(str) | §2.4 `to_twd`, step 1 tests |
| G3 rate precision / tolerance | §2.4 (6 dp, compute from stored rate, ±1 all rows), step 4 test |
| G4 edit default 幣別 / blank country | §2.5, step 4 tests |
| G5 has_fx_columns cost | §2.2 (`df.attrs`, zero API calls), step 2a test |
| G6 CSS grid for widgets | §2.1/§2.2 stacked widgets; HTML only for static tiles (§3.2) |
| G7 active-trip default | §3.2 badge + tie-break; §6 Q6 |
| G8 test tooling/cases | step 0 + per-step tables |
| G9 cache semantics / 12 s | §2.3 |
| G10 today vs 日期 | §2.3, §2.7, §6 Q3 |
| G11 migration preconditions | §2.4 script, step 2b |
| G12 badge/theme/min_value | §3.2, §2.2 |
| G13 台灣 trips | §3.3 `detect_trips`, step 8 |
| G14 tab persistence | §3.2 chrome, §6 Q2 |
| G15 last_good_df / fee toggle | §2.4 guard, §2.2 `add_fx_fee_{country}`, step 5 test |