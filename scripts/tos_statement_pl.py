#!/usr/bin/env python3
"""Realized P&L from a thinkorswim Account Statement CSV — an independent
check on the Reports page, computed from the statement alone (no Schwab
API, no app code).

    uv run python -m scripts.tos_statement_pl STATEMENT.csv OUTDIR

Writes daily/monthly/per-symbol/per-ticker P&L, a statement reconciliation
and every matched trade as CSVs in OUTDIR, and prints the totals.

Method:
- Options: opening and closing fills from Account Trade History, matched
  oldest first. Contracts expiring on or before the statement's last day
  close at 0 on their expiry, so expired and assigned options keep their
  premium. Some calendar rolls are exported with both legs on one contract
  (quantity doubled, both legs at their average price, net .00); those are
  rebuilt from the order's net cash (see rebuild_calendar_rolls).
- Stock: fills from the Cash Balance ledger (EXP rows from assignments,
  plus TRD rows), matched oldest first, longs and shorts. Shares held
  before the statement start with unknown cost, and their sales are
  reported but left out of P&L.
- Futures: the daily ADJ mark-to-market rows from Futures Statements, so
  open positions count too (unlike the Reports page, which counts futures
  when they close).
- Fees (Misc + Commissions) and income (DOI rows: interest, dividends,
  margin interest) are their own categories. Transfers and money-fund
  trades are never included.

How it differs from the Reports page, by design: no premium from options
opened before the statement, no cost basis for shares bought before it,
futures marked to market, and fees and income included.
"""

import collections
import csv
import datetime as dt
import os
import re
import sys

MON = {m: i + 1 for i, m in enumerate('JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split())}
CATS = ['option', 'stock', 'futures', 'fees', 'income']


def money(s):
    s = (s or '').strip().replace('$', '').replace(',', '')
    if s in ('', '--'):
        return 0.0
    neg = s.startswith('(') or s.startswith('-')
    return -float(s.strip('()-')) if neg else float(s.strip('()-'))


def day_of(s):
    return dt.datetime.strptime(s.split()[0], '%m/%d/%y').date()


def option_expiry(s):
    m = re.search(r'(\d{1,2}) ([A-Z]{3}) (\d{2})', s)
    return dt.date(2000 + int(m.group(3)), MON[m.group(2)], int(m.group(1)))


def contract_label(key):
    sym, exp, strike, typ = key
    if sym.startswith('/'):
        return re.sub(r'\s*\([^)]*\)', '', sym) + f' {strike} {typ}'
    return f'{sym} {exp} {strike} {typ}'


def underlying(sym):
    return sym.split()[0][:3] if sym.startswith('/') else sym


def multiplier(sym):
    m = re.search(r'1/(\d+)', sym)
    return int(m.group(1)) if sym.startswith('/') and m else 100


def rebuild_calendar_rolls(events, cash, fut):
    """thinkorswim exports some calendar rolls with both legs on one
    contract: quantity doubled, both legs at their average price a, net
    price .00. The order's net cash (Cash Balance or Futures Statements row
    at the same date and time) still holds the real credit, so each leg is
    half the quantity, with open price a + d/2 and close price a - d/2,
    where d = open - close = -cash / (signed open qty * multiplier).
    Rewrites `events` in place, the closing leg first; returns how many
    rolls it rebuilt."""
    netcash = collections.Counter()
    for r in cash:
        if r[2] == 'TRD' and re.search(r'\b(CALL|PUT)\b', r[4]):
            netcash[(day_of(r[0]), r[1])] += money(r[7])
    for r in fut:
        if r[3] == 'TRD' and re.search(r'\b(CALL|PUT)\b', r[5]):
            netcash[(day_of(r[1]), r[2])] += money(r[8])
    legs = collections.defaultdict(list)
    for i, (t, kind, p) in enumerate(events):
        if kind == 'opt':
            legs[(t, p['key'])].append(i)
    rebuilt = 0
    for (t, _key), idx in legs.items():
        if len(idx) != 2:
            continue
        a, b = events[idx[0]][2], events[idx[1]][2]
        if {a['eff'], b['eff']} != {'TO OPEN', 'TO CLOSE'} or a['q'] != -b['q'] or a['px'] != b['px'] or a['q'] % 2:
            continue
        net = netcash.get((t.date(), t.strftime('%H:%M:%S')))
        if net is None:
            continue
        op, cl = (a, b) if a['eff'] == 'TO OPEN' else (b, a)
        oq = op['q'] // 2
        diff = -net / (oq * op['m'])
        events[idx[0]] = (t, 'opt', dict(cl, q=-oq, px=round(op['px'] - diff / 2, 4)))
        events[idx[1]] = (t, 'opt', dict(op, q=oq, px=round(op['px'] + diff / 2, 4)))
        rebuilt += 1
    return rebuilt


def compute(text):
    """Parse a statement's text; return its output tables and totals."""
    lines = text.split('\n')

    def find(title):
        for i, line in enumerate(lines):
            if line.strip() == title:
                return i
        raise SystemExit('section not found: ' + title)

    def section(title):
        i = find(title) + 1
        j = i
        while j < len(lines) and lines[j].strip() != '' and not (
                j > i and re.match(r'^[A-Z][A-Za-z &/]+$', lines[j].strip())):
            j += 1
        return list(csv.reader(lines[i:j]))

    cash = [r for r in section('Cash Balance') if len(r) > 7]
    fut = [r for r in section('Futures Statements') if len(r) > 9]
    trade_history = list(csv.reader(lines[find('Account Trade History') + 2:find('Equities')]))
    held = {}
    for r in csv.reader(lines[find('Equities') + 2:find('Options')]):
        if len(r) > 3 and r[0] and r[2]:
            held[r[0]] = float(r[2].replace('+', '').replace(',', ''))
    pl_i = find('Profits and Losses') + 1
    pl_rows = list(csv.reader(lines[pl_i:find('Account Summary')]))
    open_pl = ytd_pl = 0.0
    for r in pl_rows:
        if len(r) > 5 and r[1] == 'OVERALL TOTALS':
            open_pl, ytd_pl = money(r[2]), money(r[5])
    last_day = max(day_of(r[0]) for r in cash if re.match(r'\d', r[0]))

    events = []
    cur = None
    for r in trade_history:
        if len(r) < 12:
            continue
        if r[1]:
            cur = r[1]
        if r[5] not in ('TO OPEN', 'TO CLOSE') or r[9] not in ('CALL', 'PUT'):
            continue
        t = dt.datetime.strptime(cur, '%m/%d/%y %H:%M:%S')
        key = (r[6], r[7], r[8], r[9])
        events.append((t, 'opt', dict(key=key, q=int(r[4]), px=float(r[10] or 0), eff=r[5], und=underlying(r[6]),
                                      m=multiplier(r[6]), exp=option_expiry(r[6] if r[6].startswith('/') else r[7]))))
    expiries = {p['key']: p['exp'] for _t, _k, p in events}
    for key, e in expiries.items():
        if e <= last_day:
            events.append((dt.datetime.combine(e, dt.time(23, 59)), 'expire', dict(key=key)))
    for r in cash:
        if r[2] in ('EXP', 'TRD') and re.match(r'(BOT|SOLD) ', r[4]) and not re.search(r'\b(CALL|PUT)\b', r[4]):
            m = re.match(r'(BOT|SOLD) (-?[\d.]+) (\S+)', r[4])
            q = abs(float(m.group(2))) * (1 if m.group(1) == 'BOT' else -1)
            if m.group(3) in ('SNSXX', 'SNVXX') or m.group(3).startswith('SW'):
                continue
            events.append((dt.datetime.combine(day_of(r[0]), dt.time(12 if r[2] == 'TRD' else 0)), 'stk',
                           dict(sym=m.group(3), q=q, px=abs(money(r[7])) / abs(q))))
    rebuilt = rebuild_calendar_rolls(events, cash, fut)
    events.sort(key=lambda x: (x[0], 1 if x[1] == 'expire' else 0))

    # Lots are [signed qty, price, open day]; a price of None is a holding
    # from before the statement, cost unknown.
    optlots = collections.defaultdict(list)
    stk = collections.defaultdict(list)
    flow = collections.Counter()
    for _t, kind, p in events:
        if kind == 'stk':
            flow[p['sym']] += p['q']
    for s in set(held) | set(flow):
        start = held.get(s, 0) - flow[s]
        if abs(start) > 1e-9:
            stk[s].append([start, None, None])
    real, legacy, unmatched, matches = [], [], [], []

    def fifo(lots, q, px, m, day, cls, und, label):
        while abs(q) > 1e-9 and lots and lots[0][0] * q < 0:
            lq, lp, lday = lots[0]
            mq = min(abs(q), abs(lq)) * (1 if lq > 0 else -1)
            side = 'long' if lq > 0 else 'short'
            if lp is None:
                legacy.append((day, und, mq, px))
                matches.append((und, cls, label, side, abs(mq), None, None, day, px, None,
                                'Cost basis unknown (shares held before the statement)'))
            else:
                pnl = (px - lp) * mq * m
                real.append((day, cls, und, pnl))
                matches.append((und, cls, label, side, abs(mq), lday, lp, day, px, pnl, ''))
            lots[0][0] -= mq
            q += mq
            if abs(lots[0][0]) < 1e-9:
                lots.pop(0)
        if abs(q) > 1e-9:
            lots.append([q, px, day])

    for t, kind, p in events:
        if kind == 'opt':
            lots = optlots[p['key']]
            if p['eff'] == 'TO CLOSE' and not any(lot[0] * p['q'] < 0 for lot in lots):
                unmatched.append((t.date(), p['key'], p['q'], p['px']))
                continue
            fifo(lots, p['q'], p['px'], p['m'], t.date(), 'option', p['und'], contract_label(p['key']))
        elif kind == 'expire':
            lots = optlots[p['key']]
            for lq, lp, lday in lots:
                pnl = -lp * lq * multiplier(p['key'][0])
                real.append((t.date(), 'option', underlying(p['key'][0]), pnl))
                matches.append((underlying(p['key'][0]), 'option', contract_label(p['key']),
                                'long' if lq > 0 else 'short', abs(lq), lday, lp, t.date(), 0, pnl,
                                'Expired or assigned'))
            lots.clear()
        else:
            fifo(stk[p['sym']], p['q'], p['px'], 1, t.date(), 'stock', p['sym'], p['sym'] + ' shares')
    for r in fut:
        if r[3] == 'ADJ':
            real.append((day_of(r[0]), 'futures', underlying(r[5].split(':')[0]), money(r[8])))
        if r[3] == 'TRD':
            real.append((day_of(r[0]), 'fees', 'fees', money(r[6]) + money(r[7])))
    for r in cash:
        if r[2] == 'TRD':
            real.append((day_of(r[0]), 'fees', 'fees', money(r[5]) + money(r[6])))
        if r[2] == 'DOI':
            real.append((day_of(r[0]), 'income', 'income', money(r[7])))

    by = collections.defaultdict(collections.Counter)
    for day, c, _u, v in real:
        by[day][c] += v
    daily, cum = [], 0.0
    for day in sorted(by):
        row = {c: round(by[day][c], 2) for c in CATS}
        total = round(sum(row.values()), 2)
        cum += total
        daily.append(dict(date=day.isoformat(), total=total, cumulative=round(cum, 2), **row))
    trading = [(day, u, v) for day, c, u, v in real if c in ('option', 'stock', 'futures')]
    by_symbol = collections.Counter()
    for _day, u, v in trading:
        by_symbol[u] += v
    monthly = collections.Counter()
    for r in daily:
        monthly[r['date'][:7]] += r['total']
    totals = {c: sum(by[x][c] for x in by) for c in CATS}

    day_symbol = collections.defaultdict(float)
    for day, u, v in trading:
        day_symbol[(day, u)] += v
    running = collections.Counter()
    day_symbol_rows = []
    for (day, u), v in sorted(day_symbol.items(), key=lambda x: (x[0][1], x[0][0])):
        running[u] += v
        day_symbol_rows.append(dict(date=day.isoformat(), symbol=u, pnl=round(v, 2), cumulative=round(running[u], 2)))
    month_symbol = collections.defaultdict(float)
    for (day, u), v in day_symbol.items():
        month_symbol[(day.strftime('%Y-%m'), u)] += v

    by_cat = collections.defaultdict(collections.Counter)
    for day, c, u, v in real:
        if c in ('option', 'stock', 'futures'):
            by_cat[u][c] += v
    statement = collections.defaultdict(lambda: [0.0, 0.0])
    for r in pl_rows[1:]:
        if r and r[0] and len(r) > 5 and r[1] != 'OVERALL TOTALS':
            u = r[0][:3] if r[0].startswith('/') else r[0]
            statement[u][0] += money(r[2])
            statement[u][1] += money(r[5])
    tickers = []
    for u in set(by_cat) | {k for k, v in statement.items() if abs(v[0]) > 0.005 or abs(v[1]) > 0.005}:
        c = by_cat[u]
        tickers.append(dict(symbol=u, option=round(c['option'], 2), stock=round(c['stock'], 2),
                            futures=round(c['futures'], 2), realized=round(c['option'] + c['stock'] + c['futures'], 2),
                            open_pl=round(statement[u][0], 2), statement_ytd=round(statement[u][1], 2)))
    tickers.sort(key=lambda r: -r['realized'])

    groups = collections.defaultdict(list)
    for mt in matches:
        groups[(mt[0], mt[1])].append(mt)
    match_rows, n = [], 0
    for (u, kind) in sorted(groups, key=lambda k: (k[0], 0 if k[1] == 'option' else 1)):
        rows = sorted(groups[(u, kind)], key=lambda m: m[7], reverse=True)
        n += 1
        match_rows.append(dict(id=n, symbol=u, kind=kind, contract='Total',
                               pnl=round(sum(m[9] for m in rows if m[9] is not None), 2),
                               note='Sum of the rows below that have a P&L'))
        for (_u, _k, label, side, q, od, op, cd, cp, pnl, note) in rows:
            n += 1
            match_rows.append(dict(id=n, symbol=u, kind=kind, contract=label, side=side,
                                   qty=int(q) if float(q).is_integer() else q,
                                   opened=od.isoformat() if od else '', open_px='' if op is None else round(op, 4),
                                   closed=cd.isoformat(), close_px=round(cp, 4),
                                   pnl='' if pnl is None else round(pnl, 2), note=note))

    tables = {
        'daily_pnl.csv': (daily, ['date', 'total', 'cumulative'] + CATS),
        'monthly_pnl.csv': ([dict(month=k, pnl=round(v, 2)) for k, v in sorted(monthly.items())], ['month', 'pnl']),
        'pnl_by_symbol.csv': ([dict(symbol=k, pnl=round(v, 2)) for k, v in sorted(by_symbol.items(), key=lambda x: -x[1])],
                              ['symbol', 'pnl']),
        'reconciliation.csv': ([
            dict(item='Realized trading P&L (options, stock, futures)',
                 amount=round(totals['option'] + totals['stock'] + totals['futures'], 2)),
            dict(item='Commissions and fees', amount=round(totals['fees'], 2)),
            dict(item='Dividends and interest', amount=round(totals['income'], 2)),
            dict(item='Open P/L per statement (not in the curve)', amount=open_pl),
            dict(item='Statement P/L YTD', amount=ytd_pl)], ['item', 'amount']),
        'pnl_day_symbol.csv': (day_symbol_rows, ['date', 'symbol', 'pnl', 'cumulative']),
        'pnl_month_symbol.csv': ([dict(month=m, symbol=u, pnl=round(v, 2)) for (m, u), v in sorted(month_symbol.items())],
                                 ['month', 'symbol', 'pnl']),
        'pnl_ticker.csv': (tickers, ['symbol', 'option', 'stock', 'futures', 'realized', 'open_pl', 'statement_ytd']),
        'pnl_matches.csv': (match_rows, ['id', 'symbol', 'kind', 'contract', 'side', 'qty', 'opened', 'open_px',
                                         'closed', 'close_px', 'pnl', 'note']),
    }
    return dict(tables=tables, totals=totals, open_pl=open_pl, ytd_pl=ytd_pl, last_day=last_day,
                rebuilt=rebuilt, legacy=len(legacy), unmatched=len(unmatched))


def main(argv):
    src, out = argv[1], argv[2]
    os.makedirs(out, exist_ok=True)
    with open(src, encoding='utf-8-sig') as f:
        result = compute(f.read())
    for name, (rows, cols) in result['tables'].items():
        with open(os.path.join(out, name), 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            writer.writerows(rows)
    totals = result['totals']
    print('net', round(sum(totals.values()), 2), {k: round(v, 2) for k, v in totals.items()})
    print('open P/L', result['open_pl'], 'statement YTD', result['ytd_pl'], 'through', result['last_day'])
    print('calendar rolls rebuilt:', result['rebuilt'])
    print('legacy stock closes (basis unknown):', result['legacy'], '| unmatched option closes:', result['unmatched'])


if __name__ == '__main__':
    main(sys.argv)
