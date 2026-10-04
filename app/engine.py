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


def clean(raw, mapping=UCI_MAPPING):
    """Order lines (columns named by `mapping`, see app/mapping.py) -> one row per invoice.
    Drops returns and cancellations (quantity <= 0), zero/negative prices, lines without a customer
    and lines whose date does not parse. No 'C'-prefix rule: in UCI all 19,494 'C' lines already
    have quantity <= 0, and in other exports a 'C' prefix can be a normal invoice number."""
    df = raw[[mapping[k] for k in LINE_COLS]].set_axis(LINE_COLS, axis=1)
    df['invoice_id'] = df['invoice_id'].astype(str)
    df['date'] = pd.to_datetime(df['date'], errors='coerce', format='mixed')
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce')
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df = df[(df['quantity'] > 0) & (df['price'] > 0) & df['customer_id'].notna() & df['date'].notna()]
    df = df.assign(rev=df['quantity'] * df['price'])
    inv = df.groupby(['customer_id', 'invoice_id']).agg(date=('date', 'min'), amount=('rev', 'sum')).reset_index()
    inv['date'] = inv['date'].dt.normalize()
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
