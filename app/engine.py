"""Cleaning, customer features, repeat-purchase model and backtest.

Moved from experiments/customer_repeat.py without changing the method.
Invoice-level standard schema: customer_id, invoice_id, date, amount.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

HORIZON = 56  # predict an order within the next 8 weeks
FEATURES = ['recency', 'tenure', 'n90', 'lograv', 'logn']


def load_uci(path):
    """Raw UCI Online Retail II lines: both xlsx sheets concatenated, or a csv."""
    if str(path).lower().endswith('.csv'):
        return pd.read_csv(path, parse_dates=['InvoiceDate'])
    sheets = pd.read_excel(path, sheet_name=None, engine='openpyxl')
    return pd.concat(sheets.values(), ignore_index=True)


UCI_MAPPING = {'customer_id': 'Customer ID', 'invoice_id': 'Invoice', 'date': 'InvoiceDate',
               'quantity': 'Quantity', 'price': 'Price'}
LINE_COLS = list(UCI_MAPPING)

_TIME = r'(?:[ T](\d{1,2}:\d{2}(?::\d{2})?))?'
_YEAR_FIRST = r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})' + _TIME + '$'          # 2009-12-01, 2009/12/01 07:45
_YEAR_LAST = r'^(\d{1,2})([-/.])(\d{1,2})\2(\d{4}|\d{2})' + _TIME + '$'    # 05/01/2030, 05-01-2030, 05.01.2030
MAX_BAD_DATES = 0.01


def _iso(y, m, d, t):
    return y + '-' + m.str.zfill(2) + '-' + d.str.zfill(2) + (' ' + t).fillna('')


def parse_dates(col):
    """Read a date column. Returns (datetimes, warnings); raises ValueError when the file must be refused.
    Only all-text columns are interpreted. Datetime columns (and mixed or numeric ones) keep the old behavior."""
    if pd.api.types.is_datetime64_any_dtype(col):
        return col, []
    vals = col.dropna()
    if pd.api.types.is_numeric_dtype(col) or not vals.map(lambda v: isinstance(v, str)).all():
        return pd.to_datetime(col, errors='coerce', format='mixed'), []
    s = col.astype('string').str.strip().replace('', pd.NA)
    out = pd.Series(pd.NaT, index=col.index, dtype='datetime64[ns]')
    warnings = []

    yf = s.str.extract(_YEAR_FIRST)                                   # a. year first
    ok = yf[0].notna()
    out[ok] = pd.to_datetime(_iso(yf.loc[ok, 0], yf.loc[ok, 1], yf.loc[ok, 2], yf.loc[ok, 3]),
                             errors='coerce', format='ISO8601')

    yl = s.str.extract(_YEAR_LAST)                                    # b./c. year last
    ok = yl[0].notna()
    short = ok & (yl[3].str.len() == 2)
    if short.any():
        i = short.idxmax()
        raise ValueError(f'2-digit year in the date column (row {i}: {s[i]!r}); use 4-digit years')
    if ok.any():
        first, second = yl.loc[ok, 0].astype(int), yl.loc[ok, 2].astype(int)
        if (first > 12).any() and (second > 12).any():
            i, j = (first > 12).idxmax(), (second > 12).idxmax()
            raise ValueError(f'the date column mixes day-first (row {i}: {s[i]!r}) and month-first '
                             f'(row {j}: {s[j]!r}) dates; export the dates in one format')
        dayfirst = not (second > 12).any()
        if not (first > 12).any() and not (second > 12).any():
            warnings.append('no date has a day above 12, so day or month first cannot be told apart; '
                            'read as day-first (05/01/2030 = 5 January 2030)')
        day, month = (yl.loc[ok, 0], yl.loc[ok, 2]) if dayfirst else (yl.loc[ok, 2], yl.loc[ok, 0])
        out[ok] = pd.to_datetime(_iso(yl.loc[ok, 3], month, day, yl.loc[ok, 4]), errors='coerce', format='ISO8601')

    bad = s.notna() & out.isna()                                      # d. unreadable values
    if bad.sum() > MAX_BAD_DATES * s.notna().sum():
        i = bad.idxmax()
        raise ValueError(f'{bad.sum()} of {s.notna().sum()} dates could not be read (e.g. row {i}: {s[i]!r}); '
                         f'more than {MAX_BAD_DATES:.0%}')
    if bad.any():
        warnings.append(f'{bad.sum()} rows with unreadable dates were dropped')
    return out, warnings


def clean(raw, mapping=UCI_MAPPING):
    """Order lines (columns named by `mapping`, see app/mapping.py) -> one row per invoice.
    Drops returns and cancellations (quantity <= 0), zero/negative prices, lines without a customer
    and lines whose date does not parse. No 'C'-prefix rule: in UCI all 19,494 'C' lines already
    have quantity <= 0, and in other exports a 'C' prefix can be a normal invoice number.
    Date warnings (see parse_dates) are returned in inv.attrs['warnings']."""
    df = raw[[mapping[k] for k in LINE_COLS]].set_axis(LINE_COLS, axis=1)
    df['invoice_id'] = df['invoice_id'].astype(str)
    df['date'], warnings = parse_dates(df['date'])
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce')
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df = df[(df['quantity'] > 0) & (df['price'] > 0) & df['customer_id'].notna() & df['date'].notna()]
    df = df.assign(rev=df['quantity'] * df['price'])
    inv = df.groupby(['customer_id', 'invoice_id']).agg(date=('date', 'min'), amount=('rev', 'sum')).reset_index()
    inv['date'] = inv['date'].dt.normalize()
    inv.attrs['warnings'] = warnings
    return inv


def features(inv, origin, horizon=HORIZON):
    """Features from invoices before `origin`, label = ordered in [origin, origin + horizon).
    Only customers with >= 2 prior orders are kept."""
    past = inv[inv['date'] < origin]
    g = past.groupby('customer_id')
    f = pd.DataFrame({'n': g.size(), 'last': g['date'].max(), 'first': g['date'].min(),
                      'rev': g['amount'].sum()})
    f['recency'] = (origin - f['last']).dt.days
    f['tenure'] = (origin - f['first']).dt.days
    recent = past[past['date'] >= origin - pd.Timedelta(days=90)].groupby('customer_id').size()
    f['n90'] = recent.reindex(f.index).fillna(0)
    f['lograv'] = np.log1p(f['rev'] / f['n'])
    f['logn'] = np.log1p(f['n'])
    f = f[f['n'] >= 2].copy()
    fut = inv[(inv['date'] >= origin) & (inv['date'] < origin + pd.Timedelta(days=horizon))]
    f['y'] = f.index.isin(fut['customer_id'].unique()).astype(int)
    return f


def fit(train):
    mu, sd = train[FEATURES].mean(), train[FEATURES].std() + 1e-9
    m = LogisticRegression(max_iter=1000, C=1.0)
    m.fit((train[FEATURES] - mu) / sd, train['y'])
    return m, mu, sd


def predict(fitted, df):
    m, mu, sd = fitted
    return m.predict_proba((df[FEATURES] - mu) / sd)[:, 1]


def default_origins(inv, horizon=HORIZON):
    """Three test origins: end - h, end - h - 91, end - h - 182."""
    end = inv['date'].max()
    return [end - pd.Timedelta(days=horizon + k) for k in (0, 91, 182)]


def backtest(inv, horizon=HORIZON, origins=None):
    """Each test origin o is trained only on origins o - h*{1,2,3}, whose outcome windows end before o."""
    origins = default_origins(inv, horizon) if origins is None else origins
    out = []
    for o in origins:
        te = features(inv, o, horizon)
        tr = pd.concat([features(inv, o - pd.Timedelta(days=horizon * i), horizon) for i in (1, 2, 3)])
        out.append({'origin': o, 'y': te['y'].values, 'p': predict(fit(tr), te),
                    's_recency': -te['recency'].values})
    return out


def top_k_hit(y, s, frac=0.2):
    """Share of positives among the top `frac` by score."""
    k = max(1, int(len(y) * frac))
    return y[np.argsort(-s)[:k]].mean()


def calibration(y, p, n_bins=10):
    """Equal-width probability bins: count, mean predicted, observed rate."""
    b = np.minimum((np.asarray(p) * n_bins).astype(int), n_bins - 1)
    t = pd.DataFrame({'bin': b, 'p': p, 'y': y}).groupby('bin').agg(
        n=('y', 'size'), pred=('p', 'mean'), obs=('y', 'mean'))
    t.index = [f'{i / n_bins:.1f}-{(i + 1) / n_bins:.1f}' for i in t.index]
    t['gap'] = t['obs'] - t['pred']
    return t


def ece(table):
    return float((table['n'] * table['gap'].abs()).sum() / table['n'].sum())
