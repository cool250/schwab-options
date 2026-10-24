"""The thinkorswim-statement P&L check (scripts/tos_statement_pl.py), on a
small made-up statement."""

import pytest

from scripts.tos_statement_pl import compute

# Sold 10 QQQ 29 APR 610 calls at 17.90, then rolled them on 4/28 for a
# $0.10 credit (really: bought back at 45.11, sold again at 45.21). The
# export shows that roll as one contract: qty 20 each way at the 45.16
# average, net .00 — only the cash row holds the real credit. The new
# calls expire (are assigned) on 4/29.
STATEMENT = """Account Statement for 123 (Brokerage) since 4/1/26 through 4/30/26

Cash Balance
DATE,TIME,TYPE,REF #,DESCRIPTION,Misc Fees,Commissions & Fees,AMOUNT,BALANCE
4/14/26,06:46:06,TRD,="1",SOLD -10 QQQ 100 29 APR 26 610 CALL @17.90,,,"17,900.00","17,900.00"
4/28/26,07:50:14,TRD,="2",SOLD -10 CALENDAR QQQ 100 (Weeklys) 29 APR 26 610 CALL @.10,,,100.00,"18,000.00"
4/30/26,22:00:00,BAL,,Cash balance at the start of business day 01.05 CST,,,,"18,000.00"

Futures Statements
Trade Date,Exec Date,Exec Time,Type,Ref #,Description,Misc Fees,Commissions & Fees,Amount,Balance

Account Trade History
,Exec Time,Spread,Side,Qty,Pos Effect,Symbol,Exp,Strike,Type,Price,Net Price,Order Type
,4/14/26 06:46:06,SINGLE,SELL,-10,TO OPEN,QQQ,29 APR 26,610,CALL,17.90,17.90,LMT
,4/28/26 07:50:14,CUSTOM,SELL,-20,TO OPEN,QQQ,29 APR 26,610,CALL,45.16,.00,LMT
,,,BUY,+20,TO CLOSE,QQQ,29 APR 26,610,CALL,45.16,,

Equities
Symbol,Description,Qty,Trade Price,Mark,Mark Value

Options
Symbol,Option Code,Exp,Strike,Type,Qty,Trade Price,Mark,Mark Value

Profits and Losses
Symbol,Description,P/L Open,P/L %,P/L Day,P/L YTD,P/L Diff,Margin Req,Mark Value
,OVERALL TOTALS,$0.00,0.00%,$0.00,"$18,000.00","$18,000.00",$0.00,$0.00

Account Summary
"""


def test_calendar_roll_exported_on_one_contract_is_rebuilt_from_its_cash():
    result = compute(STATEMENT)
    assert result['rebuilt'] == 1
    rows, _ = result['tables']['pnl_matches.csv']
    trades = [(r['open_px'], r['close_px'], r['qty'], r['pnl']) for r in rows if r['contract'] != 'Total']
    # The original calls bought back at 45.11, the new ones sold at 45.21.
    assert sorted(trades) == sorted([(17.9, 45.11, 10, pytest.approx(-27210.0)),
                                      (45.21, 0, 10, pytest.approx(45210.0))])
    # Options P&L is the cash collected: 17,900 + 100.
    assert result['totals']['option'] == pytest.approx(18000.0)
