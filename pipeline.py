from pathlib import Path
import csv, sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
import matplotlib.pyplot as plt

BASE = Path.cwd()
OUT = BASE / 'outputs'
OUT.mkdir(exist_ok=True)

def cents(value):
    # Exact cents; never silently round or use floating-point money.
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or abs(number) > Decimal('1000000000000'):
            return None
        scaled = number * 100
        return int(scaled) if scaled == scaled.to_integral_value() else None
    except (InvalidOperation, ValueError, OverflowError):
        return None

def valid_date(value):
    try:
        text = str(value).strip()
        result = date.fromisoformat(text)
        return text if result.isoformat() == text else None
    except ValueError:
        return None

con = sqlite3.connect(':memory:')
con.create_function('cents', 1, cents)
con.create_function('valid_date', 1, valid_date)
con.execute('CREATE TABLE raw_payments(source_row TEXT, payment_id TEXT, department TEXT, payment_date TEXT, amount TEXT)')
with (BASE / 'messy_payments.csv').open(newline='') as file:
    records = list(csv.DictReader(file))
con.executemany('INSERT INTO raw_payments VALUES (?,?,?,?,?)', [tuple(r.values()) for r in records])
con.executescript((BASE / 'clean_payments.sql').read_text())

def count(table):
    return con.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

raw_count, duplicates, rejected, accepted = [count(t) for t in
    ['raw_payments', 'duplicate_log', 'rejected_payments', 'clean_payments']]
total = con.execute('SELECT SUM(amount_cents) FROM clean_payments').fetchone()[0]
assert raw_count == duplicates + rejected + accepted
assert (raw_count, duplicates, rejected, accepted, total) == (12, 1, 6, 5, 320000)
assert cents('1.005') is None and cents('NaN') is None
assert valid_date('2026-02-30') is None
assert con.execute('SELECT COUNT(DISTINCT payment_id) FROM clean_payments').fetchone()[0] == accepted
# Re-running the transformations must reproduce the same result.
before = con.execute('SELECT * FROM clean_payments ORDER BY payment_id').fetchall()
con.executescript((BASE / 'clean_payments.sql').read_text())
assert con.execute('SELECT * FROM clean_payments ORDER BY payment_id').fetchall() == before

for table in ['clean_payments','rejected_payments','duplicate_log','payment_summary']:
    cursor = con.execute('SELECT * FROM ' + table)
    with (OUT / (table + '.csv')).open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([d[0] for d in cursor.description])
        writer.writerows(cursor)

summary = con.execute('SELECT department,total_cents FROM payment_summary ORDER BY total_cents DESC').fetchall()
plt.rcParams.update({'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})
fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), layout='constrained')
fig.patch.set_facecolor('#f7f9fc')
axes[0].bar(['Accepted','Needs review','Duplicate'], [accepted,rejected,duplicates], color=['#347f83','#bd8850','#8d94a5'])
axes[0].set(title='Every source row is accounted for', ylabel='Source records', ylim=(0,8))
for i,v in enumerate([accepted,rejected,duplicates]): axes[0].text(i,v+.15,str(v),ha='center')
axes[1].barh([r[0].title() for r in summary], [r[1]/100 for r in summary], color='#547da6')
axes[1].set(title='Validated payments by department', xlabel='US dollars', xlim=(0,1550))
axes[1].invert_yaxis()
for i,(_,v) in enumerate(summary): axes[1].text(v/100+20,i,format(v/100,',.0f'),va='center')
fig.suptitle('Payment data quality | Synthetic demonstration',fontsize=15,fontweight='bold')
fig.savefig(OUT / 'payment_quality.png',dpi=180)
plt.show()
print(f'{raw_count} input = {accepted} accepted + {rejected} review + {duplicates} duplicate')
print(f'Validated total: ${total/100:,.2f}. All checks passed.')
