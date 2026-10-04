import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
df = pd.read_csv('retail.csv', parse_dates=['InvoiceDate'])
df['Invoice'] = df['Invoice'].astype(str)
df = df[~df['Invoice'].str.startswith('C') & (df['Quantity'] > 0) & (df['Price'] > 0) & df['Customer ID'].notna()]
df['rev'] = df['Quantity'] * df['Price']
inv = df.groupby(['Customer ID', 'Invoice']).agg(date=('InvoiceDate', 'min'), rev=('rev', 'sum')).reset_index()
inv['date'] = inv['date'].dt.normalize()
end = inv['date'].max(); print('last date', end.date(), 'customers', inv['Customer ID'].nunique())
H = 56  # predict purchase within next 8 weeks
def feats(origin):
    past = inv[inv['date'] < origin]
    g = past.groupby('Customer ID')
    f = pd.DataFrame({'n': g.size(), 'last': g['date'].max(), 'first': g['date'].min(), 'rev': g['rev'].sum()})
    f['recency'] = (origin - f['last']).dt.days
    f['tenure'] = (origin - f['first']).dt.days
    recent = past[past['date'] >= origin - pd.Timedelta(days=90)].groupby('Customer ID').size()
    f['n90'] = recent.reindex(f.index).fillna(0)
    f['lograv'] = np.log1p(f['rev'] / f['n'])
    f['logn'] = np.log1p(f['n'])
    f = f[f['n'] >= 2]
    fut = inv[(inv['date'] >= origin) & (inv['date'] < origin + pd.Timedelta(days=H))]['Customer ID'].unique()
    f['y'] = f.index.isin(fut).astype(int)
    return f
def lift(y, s, frac=0.2):
    k = max(1, int(len(y) * frac)); idx = np.argsort(-s)[:k]
    return y[idx].mean() / y.mean(), y[idx].mean()
cols = ['recency', 'tenure', 'n90', 'lograv', 'logn']
origins = [end - pd.Timedelta(days=H), end - pd.Timedelta(days=H+91), end - pd.Timedelta(days=H+182)]
trainfor = lambda o: [o - pd.Timedelta(days=H*i) for i in (1, 2, 3)]
for o in origins:
    te = feats(o)
    tr = pd.concat([feats(t) for t in trainfor(o)])  # trained only on origins whose outcomes are before o
    m = LogisticRegression(max_iter=1000, C=1.0)
    mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
    m.fit((tr[cols] - mu) / sd, tr['y'])
    s_model = m.predict_proba((te[cols] - mu) / sd)[:, 1]
    s_rec = -te['recency'].values  # baseline: most recent buyers first
    s_n90 = te['n90'].values + 1e-3 * (-te['recency'].values) / 1000
    y = te['y'].values
    lm, pm = lift(y, s_model); lr, pr = lift(y, s_rec)
    print(f"origin {o.date()}: n={len(te)} base_rate={y.mean():.3f} | AUC model={roc_auc_score(y, s_model):.3f} recency-rule={roc_auc_score(y, s_rec):.3f} | top20%: hit model={pm:.3f} (lift {lm:.2f}) recency={pr:.3f} (lift {lr:.2f})")
