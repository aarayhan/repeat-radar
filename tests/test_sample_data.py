"""The committed synthetic sample files: reproducible from seed 42, mappable by rules, cleanable, auditable."""
from pathlib import Path

import pandas as pd
import pytest

from app.audit import run_audit
from app.engine import clean
from app.llm import LLMUnavailable
from app.mapping import propose_mapping
from scripts.make_sample_data import make
from test_llm import FakeLLM

SAMPLES = Path(__file__).resolve().parents[1] / 'app' / 'sample_data'
FILES = ['kasir_indonesia.csv', 'ecommerce.csv']


@pytest.fixture(scope='module')
def loaded():
    out = {}
    for f in FILES:
        raw = pd.read_csv(SAMPLES / f)
        m = propose_mapping(raw, llm=FakeLLM(LLMUnavailable('none'), LLMUnavailable('none')), model='x')
        out[f] = (raw, m, clean(raw, m['mapping']) if m['source'] else None)
    return out


def test_files_match_seed_42(tmp_path):
    make(tmp_path)
    for f in FILES:
        assert (tmp_path / f).read_bytes() == (SAMPLES / f).read_bytes()


@pytest.mark.parametrize('f', FILES)
def test_rules_mapping_and_clean(loaded, f):
    raw, m, inv = loaded[f]
    assert m['source'] == 'rules' and m['problems'] == []
    assert inv.attrs['warnings'] == []                        # kasir dates have days > 12, so day-first is certain
    assert inv['customer_id'].nunique() >= 250
    assert (inv['date'].max() - inv['date'].min()).days >= 700   # about 24 months
    assert (inv.groupby('customer_id').size() == 1).any()        # one-time buyers exist


@pytest.mark.parametrize('f', FILES)
def test_enough_history_for_two_audit_windows(loaded, f):
    a = run_audit(loaded[f][2])
    assert a['status'] == 'ok' and len(a['windows']) >= 2
