import pandas as pd
import pytest

from app.engine import clean, parse_dates

T = pd.Timestamp


def _dates(values):
    out, warnings = parse_dates(pd.Series(values, dtype=object))
    return list(out), warnings


def test_a_year_first():
    got, w = _dates(['2009-12-01', '2009/12/02 07:45', '2010-1-5 10:00:30'])
    assert got == [T('2009-12-01'), T('2009-12-02 07:45'), T('2010-01-05 10:00:30')] and w == []


def test_b_day_first_when_a_first_part_is_above_12():
    got, w = _dates(['25/01/2030', '05/01/2030 10:00', '06.02.2030'])
    assert got == [T('2030-01-25'), T('2030-01-05 10:00'), T('2030-02-06')] and w == []


def test_b_month_first_when_a_second_part_is_above_12():
    got, w = _dates(['01/25/2030', '05-01-2030'])
    assert got == [T('2030-01-25'), T('2030-05-01')] and w == []


def test_b_both_orders_in_one_column_is_refused():
    with pytest.raises(ValueError, match=r"day-first \(row 1: '25/01/2030'\).*month-first \(row 2: '01/25/2030'\)"):
        _dates(['05/01/2030', '25/01/2030', '01/25/2030'])


def test_b_ambiguous_defaults_to_day_first_with_warning():
    got, w = _dates(['05/01/2030', '06.02.2030', '07-03-2030'])
    assert got == [T('2030-01-05'), T('2030-02-06'), T('2030-03-07')]
    assert len(w) == 1 and 'day-first' in w[0]


def test_c_two_digit_year_is_refused():
    with pytest.raises(ValueError, match='use 4-digit years'):
        _dates(['05/01/2030', '06/01/30'])


def test_d_unreadable_at_or_below_1pct_dropped_with_warning():
    got, w = _dates(['2030-01-05'] * 99 + ['next tuesday'])   # exactly 1%
    assert pd.isna(got[-1]) and got[0] == T('2030-01-05')
    assert w == ['1 rows with unreadable dates were dropped']


def test_d_unreadable_above_1pct_is_refused():
    with pytest.raises(ValueError, match=r"2 of 100 dates could not be read \(e.g. row 98: '31/02/2030'\)"):
        _dates(['2030-01-05'] * 98 + ['31/02/2030', 'soon'])


def test_datetime_column_untouched():
    col = pd.Series([T('2010-01-05 10:00'), T('2010-05-01')])
    out, w = parse_dates(col)
    assert out is col and w == []


def test_clean_returns_warnings_and_refuses():
    raw = pd.DataFrame({'Invoice': ['1', '2'], 'Quantity': [1, 1], 'Price': [2.0, 3.0],
                        'Customer ID': [1, 1], 'InvoiceDate': ['05/01/2030', '06/02/2030']})
    inv = clean(raw)
    assert inv['date'].tolist() == [T('2030-01-05'), T('2030-02-06')]
    assert 'day-first' in inv.attrs['warnings'][0]
    with pytest.raises(ValueError, match='mixes'):
        clean(raw.assign(InvoiceDate=['13/01/2030', '01/13/2030']))


MIXED = [T('2030-01-05'), '06/02/2030', T('2030-03-01 10:00'), None, 'not a date', T('2030-04-02')]


def test_mixed_column_warns_once_with_counts():
    out, w = parse_dates(pd.Series(MIXED, dtype=object))
    assert len(w) == 1
    assert w[0].startswith('3 sel tanggal dan 2 sel teks.') and 'Periksa file asli.' in w[0]


def test_mixed_column_parsing_unchanged():
    col = pd.Series(MIXED, dtype=object)
    out, _ = parse_dates(col)
    before = pd.to_datetime(col, errors='coerce', format='mixed')   # the behavior before the warning was added
    pd.testing.assert_series_equal(out, before)


def test_pure_datetime_and_pure_text_columns_get_no_mixed_warning():
    as_object = pd.Series([T('2030-01-05'), T('2030-02-06'), None], dtype=object)
    assert parse_dates(as_object)[1] == []
    assert parse_dates(pd.Series([T('2030-01-05'), T('2030-02-06')]))[1] == []
    assert parse_dates(pd.Series(['2030-01-05', '2030-02-06'], dtype=object))[1] == []


def test_clean_reports_mixed_warning():
    raw = pd.DataFrame({'Invoice': ['1', '2'], 'Quantity': [1, 1], 'Price': [2.0, 3.0],
                        'Customer ID': [1, 1], 'InvoiceDate': [T('2030-01-05'), '2030-02-06']})
    assert clean(raw).attrs['warnings'][0].startswith('1 sel tanggal dan 1 sel teks.')
