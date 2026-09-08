"""
Google Sheets API integration with progressive fallback
Handles data reading, writing, and fallback to CSV export
"""

import streamlit as st
import pandas as pd
import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials
import requests
import time
from datetime import datetime, date
import logging
from typing import Optional, Dict, List, Tuple, Any
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from config import (SHEET_ID, WORKSHEET_GID, SHEET_URL, COLUMN_MAPPING,
                    OPTIONAL_HEADERS, CURRENCY_META, RATE_DECIMALS)
from helpers import parse_amount, today_local, now_local, LOCAL_TZ  # noqa: F401 (re-exported for callers)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

# Expected sheet header, in sheet order (A..I). Writes are refused when any is missing.
EXPECTED_HEADERS = ['日期', '類型_1', '類型_2', '金額', '帳戶', '名稱', '國家', '地點', '備註']
# Optional foreign-currency headers (幣別 / 原幣金額 / 匯率): mapped by name when present,
# silently absent on an un-migrated sheet. OPTIONAL_HEADERS itself lives in config.py.
# internal name -> Chinese header (reverse lookup of COLUMN_MAPPING, restricted to the real header)
INTERNAL_TO_HEADER = {COLUMN_MAPPING[h]: h for h in EXPECTED_HEADERS + OPTIONAL_HEADERS}
FX_FIELDS = [COLUMN_MAPPING[h] for h in OPTIONAL_HEADERS]  # ['currency', 'orig_amount', 'fx_rate']
TEXT_FIELDS = ['description', 'category_type', 'type_1', 'account', 'country', 'location', 'notes',
               'currency']
DATE_FORMATS = ['%m/%d/%Y', '%Y-%m-%d', '%Y/%m/%d', '%m/%d/%y']
SHEET_DATE_FORMAT = '%m/%d/%Y'
EXPECTED_COLUMNS = ['date', 'type_1', 'category_type', 'amount', 'account', 'description',
                    'country', 'location', 'notes', 'currency', 'orig_amount', 'fx_rate',
                    'sheet_row', 'original_index', 'year', 'month', 'month_year', 'weekday']
RETRY_DELAYS = (1, 2, 4)


def _secret(section: str, key: Optional[str] = None, default: Any = None) -> Any:
    """Read st.secrets without raising when no secrets file exists."""
    try:
        if section not in st.secrets:
            return default
        value = st.secrets[section]
        if key is None:
            return value
        return value.get(key, default) if hasattr(value, 'get') else default
    except Exception:
        return default


def _resolve_sheet_id() -> str:
    return _secret("app", "sheet_id", SHEET_ID) or SHEET_ID


def _resolve_worksheet_gid():
    """Worksheet GID: [app] worksheet_gid from secrets (rehearsal on a copy), else config.WORKSHEET_GID."""
    gid = _secret("app", "worksheet_gid", WORKSHEET_GID)
    if gid is None or str(gid).strip() == '':
        return WORKSHEET_GID
    try:
        return int(str(gid).strip())
    except (TypeError, ValueError):
        return gid


def has_fx_columns(df: Optional[pd.DataFrame]) -> Optional[bool]:
    """
    Did the sheet the frame was loaded from carry the 幣別/原幣金額/匯率 headers?
    Reads df.attrs only (stamped by _load_from_api/_load_from_csv) — zero API calls.
    None = unknown (e.g. a last_good_df captured before deploy, or an empty frame).
    """
    if df is None:
        return None
    try:
        value = df.attrs.get('fx_headers')
    except Exception:
        return None
    return None if value is None else bool(value)


def _api_error_status(exc: Exception) -> int:
    """HTTP status of a gspread APIError (0 when unknown)."""
    resp = getattr(exc, 'response', None)
    code = getattr(resp, 'status_code', None)
    if code is None:
        code = getattr(exc, 'code', None)
    try:
        return int(code)
    except (TypeError, ValueError):
        return 0


def _with_retry(fn, *args, **kwargs):
    """Call a gspread function, retrying on 429 / 5xx with 1s/2s/4s backoff (3 attempts)."""
    last_exc = None
    for attempt, delay in enumerate(RETRY_DELAYS):
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            status = _api_error_status(e)
            if not (status == 429 or 500 <= status < 600) or attempt == len(RETRY_DELAYS) - 1:
                raise
            last_exc = e
            logger.warning(f"⚠️ Sheets API {status}, retrying in {delay}s (attempt {attempt + 1}/{len(RETRY_DELAYS)})")
            time.sleep(delay)
    raise last_exc  # pragma: no cover


def _empty_df() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype='object') for c in EXPECTED_COLUMNS})
    df['date'] = pd.to_datetime(df['date'])
    df['amount'] = df['amount'].astype('float64')
    df['orig_amount'] = df['orig_amount'].astype('float64')
    df['fx_rate'] = df['fx_rate'].astype('float64')
    df['sheet_row'] = df['sheet_row'].astype('int64')
    return df


def _fx_numeric(series: pd.Series) -> pd.Series:
    """原幣金額 / 匯率 cells -> float64 (blank/unparseable -> NaN). Deliberately NOT parse_amount."""
    text = series.astype(str).str.strip().str.replace(',', '', regex=False)
    return pd.to_numeric(text, errors='coerce').astype('float64')


def parse_dates(series: pd.Series) -> pd.Series:
    """Per-cell date parsing with an explicit format list (no inference from the first row)."""
    text = series.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=series.index, dtype='datetime64[ns]')
    for fmt in DATE_FORMATS:
        mask = out.isna()
        if not mask.any():
            break
        out.loc[mask] = pd.to_datetime(text[mask], format=fmt, errors='coerce')
    return out


def _to_date(value: Any) -> Optional[date]:
    """Coerce a date-like value (Timestamp/datetime/date/str) to a calendar date, else None."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and value != value:
            return None
        if value is pd.NaT:
            return None
    except Exception:
        pass
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'nat', 'none', 'n/a'):
        return None
    for fmt in DATE_FORMATS + ['%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M:%S']:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _format_sheet_date(value: Any) -> str:
    """Format a date-like value as MM/DD/YYYY (the sheet's convention); pass through if unparseable."""
    d = _to_date(value)
    if d is None:
        return '' if value is None else str(value)
    return d.strftime(SHEET_DATE_FORMAT)


def _clean_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value != value:
        return ''
    text = str(value).strip()
    return '' if text.lower() in ('nan', 'none', 'nat') else text


def _sheet_amount_value(value: Any):
    """Amount as a plain number for the sheet (int when integral), or None if unparseable."""
    num = parse_amount(value)
    if num is None:
        return None
    return int(num) if float(num).is_integer() else float(num)


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Decimal(str(value)) after stripping thousands separators; None when blank/unparseable."""
    if isinstance(value, Decimal):
        return None if value.is_nan() else value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value:
            return None
        return Decimal(str(value))
    text = _clean_text(value).replace(',', '')
    if not text:
        return None
    try:
        d = Decimal(text)
    except InvalidOperation:
        return None
    return None if d.is_nan() or d.is_infinite() else d


def _sheet_orig_amount_value(value: Any, currency: Any = '') -> str:
    """原幣金額 as text with the currency's decimals (JPY/KRW 0, else 2); '' when blank."""
    d = _to_decimal(value)
    if d is None:
        return ''
    code = _clean_text(currency).upper()
    decimals = CURRENCY_META.get(code, (2, 0.01))[0]
    return str(d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP))


def _sheet_currency_value(value: Any) -> str:
    """幣別 as stored: ISO code upper-cased; TWD (any case) and blanks normalise to '' (TWD-native)."""
    code = _clean_text(value).upper()
    return '' if code == 'TWD' else code


def _sheet_rate_value(value: Any) -> str:
    """匯率 as text: quantised to RATE_DECIMALS (6) dp, trailing zeros trimmed, never int-coerced."""
    d = _to_decimal(value)
    if d is None:
        return ''
    q = d.quantize(Decimal(1).scaleb(-RATE_DECIMALS), rounding=ROUND_HALF_UP)
    text = f"{q:.{RATE_DECIMALS}f}"
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text or '0'


def _col_letter(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n)[:-1]


def _pad(row: List[str], width: int) -> List[str]:
    row = list(row)
    return row + [''] * (width - len(row)) if len(row) < width else row


class SheetsAPI:
    """
    Google Sheets API client with fallback capabilities
    """

    def __init__(self):
        self.client = None
        self.worksheet = None
        self.api_available = False
        self.read_only = True
        self.init_error = None
        self.last_write_warnings: List[str] = []  # FX fields dropped by the last add/update
        self._initialize_api()

    def _initialize_api(self):
        """
        Initialize Google Sheets API with service account credentials
        Falls back gracefully if credentials are not available
        """
        self.client = None
        self.worksheet = None
        self.api_available = False
        self.read_only = True
        self.init_error = None
        try:
            # Try to get credentials from Streamlit secrets
            creds_info = _secret("google_sheets")
            if creds_info:
                credentials = Credentials.from_service_account_info(
                    creds_info,
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive.readonly"
                    ]
                )
                self.client = gspread.authorize(credentials)

                # Get sheet ID from secrets if available
                sheet_id = _resolve_sheet_id()

                # Open the spreadsheet and worksheet
                spreadsheet = _with_retry(self.client.open_by_key, sheet_id)

                # Find worksheet by GID (no fallback to another worksheet)
                worksheet_gid = _resolve_worksheet_gid()
                worksheets = _with_retry(spreadsheet.worksheets)
                logger.info(f"📋 Available worksheets: {[(ws.title, ws.id) for ws in worksheets]}")
                for ws in worksheets:
                    if str(ws.id) == str(worksheet_gid):
                        self.worksheet = ws
                        logger.info(f"✅ Found target worksheet: {ws.title}")
                        break

                if self.worksheet is not None:
                    self.api_available = True
                    self.read_only = False
                    logger.info("✅ Google Sheets API initialized successfully")
                else:
                    self.init_error = f"找不到 GID {worksheet_gid} 的工作表"
                    logger.error(f"❌ Worksheet with GID {worksheet_gid} not found; "
                                 f"available: {[(ws.title, ws.id) for ws in worksheets]}")
                    st.error(f"❌ 找不到 GID {worksheet_gid} 的工作表，已切換為唯讀模式（不會寫入其他工作表）")
            else:
                self.init_error = "未設定 Google Sheets 憑證"
                logger.info("ℹ️ No Google Sheets credentials found, using CSV fallback")

        except Exception as e:
            self.init_error = str(e)
            logger.error(f"❌ Failed to initialize Google Sheets API: {str(e)}")
            self.worksheet = None
            self.api_available = False
            self.read_only = True

    def reconnect(self):
        """Re-run the API initialisation (resets read-only mode if it succeeds)."""
        logger.info("🔄 Reconnecting to Google Sheets API...")
        self._initialize_api()
        return self.api_available

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def load_data(self) -> pd.DataFrame:
        """
        Load expense data - prioritize API since CSV requires authentication.
        Raises RuntimeError when every source fails (the caller decides what to show;
        failures must never be cached as an empty frame).
        """
        errors = []

        # Try API first since it's authenticated and available
        if self.api_available and self.worksheet is not None:
            try:
                logger.info("🚀 Loading data via Google Sheets API...")
                df = self._load_from_api()
                logger.info(f"✅ API loaded {len(df)} records")
                return df  # an empty sheet is a legitimate (empty) result
            except Exception as e:
                logger.error(f"❌ API failed: {str(e)}")
                errors.append(f"Google Sheets API 錯誤: {str(e)}")

        # CSV fallback (attempted exactly once)
        logger.info("🚀 Attempting CSV fallback...")
        try:
            df_csv = self._load_from_csv()
            logger.info(f"✅ CSV loaded {len(df_csv)} records")
            return df_csv
        except Exception as e:
            logger.error(f"❌ CSV fallback failed: {str(e)}")
            errors.append(f"CSV 備用方案失敗: {str(e)}")

        if not self.api_available:
            hint = self.init_error or f"請確認工作表 GID {_resolve_worksheet_gid()} 存在且可訪問"
            errors.append(f"Google Sheets API 不可用 ({hint})")

        raise RuntimeError("；".join(errors) if errors else "所有資料載入方法均失敗")

    def _load_from_api(self) -> pd.DataFrame:
        """Load data directly from Google Sheets API"""
        logger.info("📊 Loading data from Google Sheets API...")

        # Get all values from the worksheet
        all_values = _with_retry(self.worksheet.get_all_values)
        logger.info(f"📊 Retrieved {len(all_values)} total rows from API")

        if not all_values:
            logger.warning("⚠️ No data retrieved from API")
            return _empty_df()

        # First row is headers
        headers = [str(h).strip() for h in all_values[0]]
        # De-duplicate / name empty headers so the DataFrame stays well-formed
        seen = {}
        clean_headers = []
        for i, h in enumerate(headers):
            name = h or f'_col{i}'
            if name in seen:
                seen[name] += 1
                name = f'{name}_{seen[name]}'
            else:
                seen[name] = 0
            clean_headers.append(name)
        width = len(clean_headers)
        data_rows = [_pad(r, width)[:width] for r in all_values[1:]]

        df = pd.DataFrame(data_rows, columns=clean_headers)
        logger.info(f"📊 Raw DataFrame shape: {df.shape}")

        # Clean and process the data; remember whether the FX headers exist (from the
        # header row already in hand — no extra API call, see has_fx_columns()).
        out = self._process_data(df, source="api")
        out.attrs['fx_headers'] = all(h in headers for h in OPTIONAL_HEADERS)
        return out

    def _load_from_csv(self) -> pd.DataFrame:
        """Load data from CSV export as fallback (raises on failure)"""
        logger.info("📄 Loading data from CSV export...")

        # Construct CSV URL with specific GID
        csv_url = SHEET_URL
        sheet_id = _resolve_sheet_id()
        worksheet_gid = _resolve_worksheet_gid()
        if (sheet_id and sheet_id != SHEET_ID) or str(worksheet_gid) != str(WORKSHEET_GID):
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={worksheet_gid}"

        logger.info(f"📄 CSV URL: {csv_url}")

        response = requests.get(csv_url, timeout=10)
        logger.info(f"📄 CSV response status: {response.status_code}")
        response.raise_for_status()

        content_type = response.headers.get('content-type', '')
        if 'text/html' in content_type:
            logger.warning("📄 CSV export returned HTML (authentication required)")
            raise RuntimeError("CSV export requires authentication")

        # Decode explicitly as UTF-8 before any header check
        try:
            csv_text = response.content.decode('utf-8')
        except UnicodeDecodeError:
            csv_text = response.content.decode('utf-8', errors='replace')

        if '日期' not in csv_text[:500] or '金額' not in csv_text[:500]:
            logger.warning(f"📄 CSV response does not contain expected headers: {csv_text[:200]!r}")
            raise RuntimeError("CSV 內容不含預期欄位")

        # Read into DataFrame; keep blank lines so line i maps to sheet row i+2
        from io import StringIO
        df = pd.read_csv(StringIO(csv_text), quotechar='"', skipinitialspace=True,
                         dtype=str, keep_default_na=False, skip_blank_lines=False)

        # Try to fix column encoding if needed (mojibake headers)
        new_columns = []
        for col in df.columns:
            fixed = str(col).strip()
            if fixed not in COLUMN_MAPPING:
                try:
                    candidate = fixed.encode('latin-1').decode('utf-8')
                    if candidate in COLUMN_MAPPING:
                        logger.info(f"✅ Fixed column: {col} → {candidate}")
                        fixed = candidate
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            new_columns.append(fixed)
        df.columns = new_columns

        out = self._process_data(df, source="csv")
        out.attrs['fx_headers'] = all(h in new_columns for h in OPTIONAL_HEADERS)
        return out

    def _process_data(self, df: pd.DataFrame, source: str) -> pd.DataFrame:
        """
        Clean and process the raw data from Google Sheets.
        Output contract: 'amount' float64 (unparseable -> NaN), 'date' datetime64 (explicit formats),
        text fields str with '' for missing, 'sheet_row' = 1-based sheet row (header = row 1).
        """
        logger.info(f"🧹 Processing data from {source}: {df.shape}")

        try:
            df = df.copy()
            # Sheet row number BEFORE any row is dropped (data index 0 -> sheet row 2)
            df['sheet_row'] = (pd.RangeIndex(len(df)) + 2).astype('int64')
            df['original_index'] = pd.RangeIndex(len(df))

            # Apply column mapping (Chinese to English) - only for columns that exist
            existing_mapping = {k: v for k, v in COLUMN_MAPPING.items() if k in df.columns}
            df = df.rename(columns=existing_mapping)
            # If two source columns mapped to the same name keep the first
            df = df.loc[:, ~pd.Index(df.columns).duplicated()]
            logger.info(f"🔄 Columns after mapping: {list(df.columns)}")

            missing = [c for c in ['date', 'amount', 'description'] if c not in df.columns]
            if missing:
                logger.warning(f"⚠️ Missing expected columns: {missing}; actual: {list(df.columns)}")
                st.warning(f"⚠️ 找不到必要欄位 {missing}。實際欄位: {list(df.columns)}")

            # Text fields: NaN/None -> '' (never the literal 'nan')
            for field in TEXT_FIELDS:
                if field in df.columns:
                    df[field] = df[field].map(_clean_text)
                else:
                    df[field] = ''

            # 幣別: ISO code upper-cased; 'TWD' and blank both mean a TWD-native row
            df['currency'] = df['currency'].map(lambda s: '' if s.upper() == 'TWD' else s.upper())

            # 原幣金額 / 匯率: plain numerics (NOT parse_amount, which strips NT$/TWD and int-coerces)
            for field in ('orig_amount', 'fx_rate'):
                if field in df.columns:
                    df[field] = _fx_numeric(df[field])
                else:
                    df[field] = pd.Series(float('nan'), index=df.index, dtype='float64')

            # Amount: tolerant parse ('26,495.00', 'NT$1,200'); unparseable -> NaN (consumers decide)
            if 'amount' in df.columns:
                raw_amount = df['amount']
                df['amount'] = pd.to_numeric(raw_amount.map(parse_amount), errors='coerce').astype('float64')
                bad = int(df['amount'].isna().sum() - raw_amount.map(_clean_text).eq('').sum())
                if bad > 0:
                    logger.warning(f"💰 {bad} amount cells could not be parsed")
            else:
                df['amount'] = pd.Series(float('nan'), index=df.index, dtype='float64')

            # Date: explicit per-cell formats
            if 'date' in df.columns:
                raw_date = df['date']
                df['date'] = parse_dates(raw_date)
                bad_dates = int(df['date'].isna().sum() - raw_date.map(_clean_text).eq('').sum())
                if bad_dates > 0:
                    logger.warning(f"📅 {bad_dates} date cells could not be parsed")
            else:
                df['date'] = pd.Series(pd.NaT, index=df.index, dtype='datetime64[ns]')

            # Drop rows with neither a usable date nor a usable amount nor a description
            rows_before = len(df)
            keep = df['date'].notna() | df['amount'].notna() | df['description'].ne('')
            df = df[keep]
            logger.info(f"📊 Removed {rows_before - len(df)} empty rows; {len(df)} remaining")

            # Add derived fields for analysis
            df['year'] = df['date'].dt.year
            df['month'] = df['date'].dt.month
            df['month_year'] = df['date'].dt.to_period('M')
            df['weekday'] = df['date'].dt.day_name()

            df['sheet_row'] = df['sheet_row'].astype('int64')

            total = float(df['amount'].sum()) if df['amount'].notna().any() else 0.0
            logger.info(f"✅ Processed {len(df)} expense records, total NT${total:,.0f}")
            return df

        except Exception as e:
            logger.error(f"❌ Error processing data: {str(e)}")
            raise RuntimeError(f"資料處理錯誤: {str(e)}") from e

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def _check_writable(self) -> bool:
        if not self.api_available or self.read_only:
            st.error("❌ Google Sheets API 未設定或不可用（唯讀模式）")
            st.info("💡 請確認已在 Streamlit Cloud 設定 secrets，或本地設定 service account 金鑰")
            return False
        if self.worksheet is None:
            st.error(f"❌ 無法連接到工作表 (GID {_resolve_worksheet_gid()})")
            st.info("💡 請確認 Google Sheet 已與 service account 共用，且有編輯權限")
            return False
        return True

    def _header_map(self) -> Optional[Tuple[Dict[str, int], int]]:
        """
        Read the header row (ONE row_values(1) call) and map internal column names -> 0-based index.
        The 9 EXPECTED_HEADERS are required (any order); the OPTIONAL_HEADERS (幣別/原幣金額/匯率)
        are mapped only when present. Returns (map, header_width) or None (with st.error).
        """
        header = [str(h).strip() for h in _with_retry(self.worksheet.row_values, 1)]
        missing = [h for h in EXPECTED_HEADERS if h not in header]
        if missing:
            logger.error(f"❌ Sheet header missing expected columns {missing}: {header}")
            st.error(f"❌ 工作表標題列缺少欄位 {missing}，為避免寫錯欄位已取消操作")
            return None
        header_map = {COLUMN_MAPPING[h]: header.index(h) for h in EXPECTED_HEADERS}
        for h in OPTIONAL_HEADERS:
            if h in header:
                header_map[COLUMN_MAPPING[h]] = header.index(h)
        return header_map, len(header)

    @staticmethod
    def _cell_value(field: str, value: Any, currency: Any = ''):
        """
        Value to write for one cell. Dates -> MM/DD/YYYY, 金額 -> number, FX cells -> text:
        幣別 upper-cased with TWD -> '' (TWD-native), 原幣金額 with the currency's decimals,
        匯率 at 6 dp trimmed (never int-coerced).
        """
        if field == 'date':
            return _format_sheet_date(value)
        if field == 'amount':
            num = _sheet_amount_value(value)
            return '' if num is None else num
        if field == 'currency':
            return _sheet_currency_value(value)
        if field == 'orig_amount':
            return _sheet_orig_amount_value(value, currency)
        if field == 'fx_rate':
            return _sheet_rate_value(value)
        return _clean_text(value)

    def _note_dropped_fx(self, header_map: Dict[str, int], data: Dict) -> None:
        """Record (in last_write_warnings) FX fields the caller supplied that the sheet cannot hold."""
        for field in FX_FIELDS:
            if field in header_map or field not in data:
                continue
            value = _clean_text(data.get(field))
            if value == '' or (field == 'currency' and value.upper() == 'TWD'):
                continue  # TWD-native rows carry nothing the sheet needs
            header = INTERNAL_TO_HEADER[field]
            msg = f"工作表沒有「{header}」欄位，已略過 {header}={value}"
            logger.warning(f"⚠️ {msg}")
            self.last_write_warnings.append(msg)

    @staticmethod
    def _row_matches(row: List[str], header_map: Dict[str, int], original: Dict) -> bool:
        """Does a sheet row match the record as loaded (description, amount, calendar day)?"""
        def cell(field):
            idx = header_map[field]
            return row[idx] if idx < len(row) else ''

        # A missing or completely blank row never "matches" anything, even a
        # record whose own description/amount/date are blank or unparseable.
        if not any(_clean_text(c) for c in row):
            return False

        if _clean_text(cell('description')) != _clean_text(original.get('description', '')):
            return False

        sheet_amt = parse_amount(cell('amount'))
        orig_amt = parse_amount(original.get('amount'))
        if sheet_amt is None or orig_amt is None:
            if not (sheet_amt is None and orig_amt is None):
                return False
        elif abs(sheet_amt - orig_amt) >= 0.5:
            return False

        # Calendar day must agree. If the record was loaded with an
        # unparseable date, the cell must still be unparseable (and vice
        # versa): a parseable date in only one of them means a different row.
        sheet_date = _to_date(cell('date'))
        orig_date = _to_date(original.get('date'))
        if (sheet_date is None) != (orig_date is None):
            return False
        if sheet_date is not None and sheet_date != orig_date:
            return False
        return True

    def _locate_row(self, sheet_row: Any, original: Dict, header_map: Dict[str, int]
                    ) -> Optional[Tuple[int, List[str]]]:
        """
        Verify that row `sheet_row` still holds `original`; otherwise search for a UNIQUE match.
        Returns (row_number, current_row_values) or None (with st.error). Never falls back positionally.
        """
        try:
            n = int(sheet_row)
        except (TypeError, ValueError):
            n = 0
        if n >= 2:
            try:
                current = _with_retry(self.worksheet.row_values, n)
            except APIError as e:
                # e.g. 400 when the row is beyond the sheet's current grid
                # (row deleted and grid trimmed): fall through to the search.
                logger.warning(f"⚠️ Could not read row {n} ({e}); searching instead")
                current = None
            if current is not None:
                if self._row_matches(current, header_map, original):
                    return n, list(current)
                logger.warning(f"⚠️ Row {n} no longer matches the selected record: {current}")

        # Search for a unique (date, description, amount) match
        all_values = _with_retry(self.worksheet.get_all_values)
        matches = [(i + 1, row) for i, row in enumerate(all_values)
                   if i >= 1 and self._row_matches(row, header_map, original)]
        if len(matches) == 1:
            logger.info(f"🎯 Record relocated to sheet row {matches[0][0]}")
            return int(matches[0][0]), list(matches[0][1])
        desc = _clean_text(original.get('description', ''))
        if not matches:
            st.error(f"❌ 找不到記錄「{desc}」，可能已被刪除或修改。請重新整理資料後再試")
        else:
            st.error(f"❌ 記錄「{desc}」在工作表中有 {len(matches)} 筆相同資料，無法確定要修改哪一筆。請重新整理資料後再試")
        return None

    @staticmethod
    def _explain_write_error(e: Exception, action: str):
        error_msg = str(e)
        if "403" in error_msg:
            st.error("❌ 權限不足：請確認 Google Sheet 已與 service account 共用")
        elif "404" in error_msg:
            st.error("❌ 找不到工作表：請確認 Sheet ID 和 GID 正確")
        else:
            st.error(f"❌ {action}失敗: {error_msg}")
            st.info("💡 請重新整理頁面後重試")

    def add_expense(self, expense_data: Dict) -> bool:
        """
        Add a new expense record to the sheet
        Returns True if successful, False otherwise
        """
        logger.info(f"🔍 Attempting to add expense: {expense_data}")
        self.last_write_warnings = []
        if not self._check_writable():
            return False

        try:
            hm = self._header_map()
            if hm is None:
                return False
            header_map, width = hm

            expense_data = dict(expense_data)
            currency = _sheet_currency_value(expense_data.get('currency', ''))
            if currency == '':
                # TWD-native (blank or 'TWD'): invariant currency == '' ⇒ 原幣金額/匯率 blank
                expense_data['orig_amount'] = ''
                expense_data['fx_rate'] = ''
            row_data = [''] * width
            for field, idx in header_map.items():
                row_data[idx] = self._cell_value(field, expense_data.get(field, ''), currency)
            # Un-migrated sheet: the TWD row is still written; FX fields are dropped and reported
            self._note_dropped_fx(header_map, expense_data)

            logger.info(f"📝 Row data to append: {row_data}")
            _with_retry(self.worksheet.append_row, row_data)
            logger.info("📝 Row appended successfully to worksheet")

            # Clear Streamlit cache to reflect changes
            st.cache_data.clear()
            return True

        except Exception as e:
            logger.error(f"❌ Failed to add expense: {str(e)}")
            self._explain_write_error(e, "新增")
            return False

    def update_expense(self, sheet_row: int, original: Dict, updated: Dict) -> bool:
        """
        Update an existing expense record identified by its sheet row, after verifying
        that the row still holds `original`. Only columns present in `updated` are changed.
        FX cells: passing currency='' or 'TWD' (幣別 -> TWD-native) writes an explicit '' into
        幣別/原幣金額/匯率 (when those columns exist); omitting the FX keys leaves the stored FX
        cells untouched.
        """
        self.last_write_warnings = []
        if not self._check_writable():
            return False

        try:
            hm = self._header_map()
            if hm is None:
                return False
            header_map, width = hm

            located = self._locate_row(sheet_row, original, header_map)
            if located is None:
                return False
            row_number, current = located
            row_number = int(row_number)

            new_row = _pad(current, width)[:width]
            updated = dict(updated)
            if 'currency' in updated and _sheet_currency_value(updated['currency']) == '':
                # 幣別 -> TWD ('' or 'TWD'): the invariant currency == '' ⇒ 原幣金額/匯率 blank must hold
                updated['currency'] = ''
                updated['orig_amount'] = ''
                updated['fx_rate'] = ''
            if 'currency' in updated:
                currency = updated['currency']
            elif 'currency' in header_map:
                currency = new_row[header_map['currency']]
            else:
                currency = ''
            for field, value in updated.items():
                if field not in header_map:
                    continue
                if field == 'amount' and _sheet_amount_value(value) is None:
                    st.error("❌ 金額無法解析，已取消更新")
                    return False
                new_row[header_map[field]] = self._cell_value(field, value, currency)
            self._note_dropped_fx(header_map, updated)

            range_name = f"A{row_number}:{_col_letter(width)}{row_number}"
            logger.info(f"📝 Updating sheet row {row_number} ({range_name}): {new_row}")
            _with_retry(self.worksheet.update, values=[new_row], range_name=range_name)
            logger.info(f"✅ Successfully updated row {row_number} in Google Sheets")

            st.cache_data.clear()
            return True

        except Exception as e:
            logger.error(f"❌ Failed to update expense: {str(e)}")
            self._explain_write_error(e, "更新")
            return False

    def delete_expense(self, sheet_row: int, original: Dict) -> bool:
        """
        Delete an expense record identified by its sheet row, after verifying
        that the row still holds `original`.
        """
        if not self._check_writable():
            return False

        try:
            hm = self._header_map()
            if hm is None:
                return False
            header_map, _ = hm

            located = self._locate_row(sheet_row, original, header_map)
            if located is None:
                return False
            row_number = int(located[0])

            logger.info(f"🗑️ Deleting sheet row {row_number}: {located[1]}")
            _with_retry(self.worksheet.delete_rows, row_number)
            logger.info(f"✅ Successfully deleted row {row_number} from Google Sheets")

            st.cache_data.clear()
            return True

        except Exception as e:
            logger.error(f"❌ Failed to delete expense: {str(e)}")
            if "404" in str(e):
                st.error("❌ 找不到該記錄：可能已被刪除")
            else:
                self._explain_write_error(e, "刪除")
            return False

    def get_status(self) -> Dict:
        """Get API status information"""
        return {
            "api_available": self.api_available,
            "read_only": self.read_only,
            "worksheet_connected": self.worksheet is not None,
            "sheet_id": _resolve_sheet_id(),
            "worksheet_gid": _resolve_worksheet_gid(),
            "error": self.init_error,
        }


# Global instance
_sheets_api = None
_last_init_attempt = 0.0
_REINIT_INTERVAL = 60  # seconds


def get_sheets_api() -> SheetsAPI:
    """
    Get or create the global SheetsAPI instance.
    A failed initialisation is retried (at most once a minute) when credentials exist,
    so a transient error does not permanently disable writes.
    """
    global _sheets_api, _last_init_attempt
    if _sheets_api is None:
        _sheets_api = SheetsAPI()
        _last_init_attempt = time.monotonic()
    elif (not _sheets_api.api_available and _secret("google_sheets")
          and time.monotonic() - _last_init_attempt > _REINIT_INTERVAL):
        _sheets_api.reconnect()
        _last_init_attempt = time.monotonic()
    return _sheets_api


@st.cache_data(ttl=60)  # Cache for 1 minute to see updates faster
def _load_expense_data_cached() -> pd.DataFrame:
    """
    Cached loader. Raises on failure so a transient error is never cached as an empty frame.
    """
    api = get_sheets_api()
    return api.load_data()


def load_expense_data() -> pd.DataFrame:
    """
    Load expense data (cached 60s). On failure show a warning and return the last good
    DataFrame from session state, or an empty frame with the expected columns.
    """
    try:
        df = _load_expense_data_cached()
        try:
            st.session_state['last_good_df'] = df
        except Exception:
            pass
        return df
    except Exception as e:
        logger.error(f"❌ load_expense_data failed: {e}")
        st.warning(f"⚠️ 資料載入失敗，顯示上次成功載入的資料: {e}")
        try:
            last = st.session_state.get('last_good_df')
        except Exception:
            last = None
        if last is not None:
            return last
        return _empty_df()


def refresh_data():
    """
    Force refresh of cached data
    """
    st.cache_data.clear()
    logger.info("🔄 Data cache cleared")


def reconnect():
    """
    Re-initialise the Google Sheets connection and clear cached data
    """
    global _last_init_attempt
    api = get_sheets_api()
    ok = api.reconnect()
    _last_init_attempt = time.monotonic()
    st.cache_data.clear()
    logger.info(f"🔄 Reconnected (api_available={ok})")
    return ok
