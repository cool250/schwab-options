"""TransactionService.get_income_and_fees: the requested days, inclusive."""


def test_rows_outside_the_range_are_dropped_and_the_last_day_is_kept(make_service):
    svc = make_service(income_fees=[
        {"date": "2026-08-31", "kind": "INCOME", "category": "INTEREST", "description": "", "amount": 1.0},
        {"date": "2026-09-30", "kind": "FEE", "category": "COMMISSION", "description": "", "amount": -2.0},
        {"date": "2026-09-01", "kind": "INCOME", "category": "DIVIDEND", "description": "", "amount": 3.0},
        {"date": "2026-10-01", "kind": "INCOME", "category": "INTEREST", "description": "", "amount": 4.0},
    ])
    rows = svc.get_income_and_fees("2026-09-01", "2026-09-30")
    assert [r["amount"] for r in rows] == [3.0, -2.0]
