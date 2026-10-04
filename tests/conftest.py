import numpy as np
import pandas as pd
import pytest


def synth_invoices(days=730, n_customers=400, seed=0):
    """Synthetic invoice history: each customer buys at their own rate during their own active period."""
    rng = np.random.default_rng(seed)
    rate = rng.lognormal(mean=-0.5, sigma=0.8, size=n_customers) / 56   # orders per day
    start = rng.integers(0, days // 2, n_customers)
    stop = np.minimum(start + rng.integers(90, days * 2, n_customers), days)  # some customers go quiet
    d = np.arange(days)
    buys = (rng.random((n_customers, days)) < rate[:, None]) & (d >= start[:, None]) & (d < stop[:, None])
    cust, day = np.nonzero(buys)
    return pd.DataFrame({
        'customer_id': cust,
        'invoice_id': [f'S{i}' for i in range(len(cust))],
        'date': pd.Timestamp('2030-01-01') + pd.to_timedelta(day, unit='D'),
        'amount': rng.gamma(2.0, 50.0, len(cust)).round(2),
    })


@pytest.fixture
def make_inv():
    return synth_invoices
