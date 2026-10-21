from pathlib import Path
import csv
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation

import matplotlib.pyplot as plt


BASE = Path.cwd()
OUT = BASE / "outputs"
OUT.mkdir(exist_ok=True)


def cents(value):
    try:
        number = Decimal(str(value).strip())

        if not number.is_finite():
            return None

        if abs(number) > Decimal("1000000000000"):
            return None

        scaled = number * 100

        if scaled != scaled.to_integral_value():
            return None

        return int(scaled)

    except (InvalidOperation, ValueError, OverflowError):
        return None


def valid_date(value):
    try:
        text = str(value).strip()
        result = date.fromisoformat(text)

        if result.isoformat() == text:
            return text

        return None

    except ValueError:
        return None


con = sqlite3.connect(":memory:")

con.create_function("cents", 1, cents)
con.create_function("valid_date", 1, valid_date)

con.execute("""
    CREATE TABLE raw_patients (
        source_row TEXT,
        payment_id TEXT,
        department TEXT,
        payment_date TEXT,
        amount TEXT
    )
""")

with (BASE / "messy_payments.csv").open(
    newline="", encoding="utf-8-sig"
) as file:
    reader = csv.DictReader(file)

    records = [
        (
            row["source_row"],
            row["payment_id"],
            row["department"],
            row["payment_date"],
            row["amount"],
        )
        for row in reader
    ]

con.executemany(
    "INSERT INTO raw_patients VALUES (?, ?, ?, ?, ?)",
    records,
)

sql = (BASE / "clean_payments.sql").read_text(encoding="utf-8")
con.executescript(sql)


def record_count(table):
    return con.execute(
        f"SELECT COUNT(*) FROM {table}"
    ).fetchone()[0]


raw_count = record_count("raw_patients")
duplicate_count = record_count("duplicate_log")
review_count = record_count("patient_review_queue")
accepted_count = record_count("clean_patients")

total_cents = con.execute("""
    SELECT COALESCE(SUM(amount_cents), 0)
    FROM clean_patients
""").fetchone()[0]


assert raw_count == (
    duplicate_count + review_count + accepted_count
), "Some source records are unaccounted for."

unique_ids = con.execute("""
    SELECT COUNT(DISTINCT payment_id)
    FROM clean_patients
""").fetchone()[0]

assert unique_ids == accepted_count, "Accepted payment IDs are not unique."

assert cents("1.005") is None
assert cents("NaN") is None
assert valid_date("2026-02-30") is None

before = con.execute("""
    SELECT *
    FROM clean_patients
    ORDER BY payment_id
""").fetchall()

con.executescript(sql)

after = con.execute("""
    SELECT *
    FROM clean_patients
    ORDER BY payment_id
""").fetchall()

assert before == after, "Repeating the SQL changed the accepted records."


exports = {
    "clean_patients": "clean_payments.csv",
    "patient_review_queue": "rejected_payments.csv",
    "duplicate_log": "duplicate_log.csv",
    "payment_summary": "payment_summary.csv",
}

for table, filename in exports.items():
    cursor = con.execute(f"SELECT * FROM {table}")

    with (OUT / filename).open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            [column[0] for column in cursor.description]
        )
        writer.writerows(cursor)


summary = con.execute("""
    SELECT department, total_cents
    FROM payment_summary
    ORDER BY total_cents DESC, department
""").fetchall()

review_reasons = con.execute("""
    SELECT disposition, COUNT(*) AS record_count
    FROM patient_review_queue
    GROUP BY disposition
    ORDER BY record_count DESC, disposition
""").fetchall()


plt.rcParams.update({
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

fig, axes = plt.subplots(
    1,
    3,
    figsize=(16, 5),
    layout="constrained",
)

fig.patch.set_facecolor("#f7f9fc")

categories = ["Accepted", "Needs review", "Duplicate"]
counts = [accepted_count, review_count, duplicate_count]

bars = axes[0].bar(
    categories,
    counts,
    color=["#347f83", "#bd8850", "#8d94a5"],
)

axes[0].bar_label(bars, padding=4)
axes[0].set_title("Where each source record went")
axes[0].set_ylabel("Number of records")
axes[0].set_ylim(0, max(counts + [1]) + 2)
axes[0].yaxis.get_major_locator().set_params(integer=True)

if summary:
    departments = [row[0].title() for row in summary]
    dollars = [row[1] / 100 for row in summary]

    bars = axes[1].barh(
        departments,
        dollars,
        color="#547da6",
    )

    axes[1].bar_label(
        bars,
        labels=[f"${value:,.2f}" for value in dollars],
        padding=4,
    )

    axes[1].invert_yaxis()
    axes[1].set_xlim(
        0, max(dollars + [1]) * 1.3
    )
else:
    axes[1].text(
        0.5, 0.5, "No accepted payments",
        ha="center", transform=axes[1].transAxes,
    )

axes[1].set_title("Validated payments by department")
axes[1].set_xlabel("US dollars")

if review_reasons:
    reasons = [row[0] for row in review_reasons]
    reason_counts = [row[1] for row in review_reasons]

    bars = axes[2].barh(
        reasons,
        reason_counts,
        color="#bd8850",
    )

    axes[2].bar_label(bars, padding=4)
    axes[2].invert_yaxis()
    axes[2].set_xlim(0, max(reason_counts) + 1)
    axes[2].xaxis.get_major_locator().set_params(integer=True)
else:
    axes[2].text(
        0.5, 0.5, "No records need review",
        ha="center", transform=axes[2].transAxes,
    )

axes[2].set_title("Why records need review")
axes[2].set_xlabel("Number of records")

fig.suptitle(
    "Payment Data Quality | Synthetic Sample",
    fontsize=16,
    fontweight="bold",
)

fig.savefig(
    OUT / "payment_quality.png",
    dpi=180,
    bbox_inches="tight",
)

plt.show()

print(f"Input records: {raw_count}")
print(f"Accepted records: {accepted_count}")
print(f"Records needing review: {review_count}")
print(f"Duplicates removed: {duplicate_count}")
print(f"Validated payment total: ${total_cents / 100:,.2f}")
print("All validation checks passed.")

con.close()
