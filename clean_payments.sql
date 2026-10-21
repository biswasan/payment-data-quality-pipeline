-- SQLite SQL. Python registers strict date and currency validators.
DROP TABLE IF EXISTS normalized;
CREATE TABLE normalized AS
SELECT *, NULLIF(TRIM(payment_id), '') AS business_id,
       LOWER(TRIM(department)) AS clean_department,
       valid_date(payment_date) AS clean_date,
       cents(amount) AS amount_cents
FROM raw_payments;

-- Only identical normalized business records are deduplicated.
DROP TABLE IF EXISTS ranked;
CREATE TABLE ranked AS
SELECT *, ROW_NUMBER() OVER (
  PARTITION BY business_id, clean_department, payment_date, amount_cents,
               CASE WHEN amount_cents IS NULL THEN amount ELSE '' END
  ORDER BY CAST(source_row AS INTEGER)) AS duplicate_rank
FROM normalized;

DROP TABLE IF EXISTS duplicate_log;
CREATE TABLE duplicate_log AS SELECT * FROM ranked WHERE duplicate_rank > 1;

-- Different versions of one payment ID require review, not guessing.
DROP TABLE IF EXISTS conflicts;
CREATE TABLE conflicts AS
SELECT business_id FROM ranked
WHERE duplicate_rank = 1 AND business_id IS NOT NULL
GROUP BY business_id HAVING COUNT(*) > 1;

DROP TABLE IF EXISTS classified;
CREATE TABLE classified AS
SELECT *, CASE
 WHEN business_id IS NULL THEN 'Missing payment ID'
 WHEN business_id IN (SELECT business_id FROM conflicts) THEN 'Conflicting payment ID'
 WHEN clean_department NOT IN ('health','transport','education') THEN 'Unknown department'
 WHEN clean_date IS NULL THEN 'Invalid date'
 WHEN amount_cents IS NULL THEN 'Invalid amount'
 WHEN amount_cents < 0 THEN 'Negative amount: review'
 ELSE 'Accepted' END AS disposition
FROM ranked WHERE duplicate_rank = 1;

DROP TABLE IF EXISTS rejected_payments;
CREATE TABLE rejected_payments AS SELECT * FROM classified WHERE disposition <> 'Accepted';
DROP TABLE IF EXISTS clean_payments;
CREATE TABLE clean_payments AS
SELECT source_row, business_id AS payment_id, clean_department AS department,
       clean_date AS payment_date, amount_cents
FROM classified WHERE disposition = 'Accepted';
DROP TABLE IF EXISTS payment_summary;
CREATE TABLE payment_summary AS
SELECT department, COUNT(*) AS payment_count, SUM(amount_cents) AS total_cents
FROM clean_payments GROUP BY department;
