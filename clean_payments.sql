DROP TABLE IF EXISTS Patient_Table; -- 1

CREATE TABLE Patient_Table AS
SELECT *,
       NULLIF(TRIM(payment_id), '') AS business_id,
       LOWER(TRIM(department)) AS clean_department,
       valid_date(payment_date) AS clean_date,
       cents(amount) AS amount_cents
FROM raw_patients;


DROP TABLE IF EXISTS ranked; -- 2

CREATE TABLE ranked AS
SELECT *,
       ROW_NUMBER() OVER (
           PARTITION BY
               business_id,
               clean_department,
               payment_date,
               amount_cents,
               CASE
                   WHEN amount_cents IS NULL THEN amount
                   ELSE ''
               END
           ORDER BY CAST(source_row AS INTEGER)
       ) AS duplicate_rank
FROM Patient_Table;


DROP TABLE IF EXISTS duplicate_log; -- 3

CREATE TABLE duplicate_log AS
SELECT *
FROM ranked
WHERE duplicate_rank > 1;


DROP TABLE IF EXISTS conflicts; -- 4

CREATE TABLE conflicts AS
SELECT business_id
FROM ranked
WHERE duplicate_rank = 1
  AND business_id IS NOT NULL
GROUP BY business_id
HAVING COUNT(*) > 1;


DROP TABLE IF EXISTS classified; -- 5

CREATE TABLE classified AS
SELECT *,
       CASE
           WHEN business_id IS NULL
               THEN 'Missing payment ID'

           WHEN business_id IN (
               SELECT business_id
               FROM conflicts
           )
               THEN 'Conflicting payment ID'

           WHEN clean_department IS NULL
                OR clean_department NOT IN (
                    'health', 'transport', 'education'
                )
               THEN 'Unknown department'

           WHEN clean_date IS NULL
               THEN 'Invalid date'

           WHEN amount_cents IS NULL
               THEN 'Invalid amount'

           WHEN amount_cents < 0
               THEN 'Negative amount: review'

           ELSE 'Accepted'
       END AS disposition
FROM ranked
WHERE duplicate_rank = 1;


DROP TABLE IF EXISTS patient_review_queue; -- 6

CREATE TABLE patient_review_queue AS
SELECT *
FROM classified
WHERE disposition <> 'Accepted';


DROP TABLE IF EXISTS clean_patients; -- 7

CREATE TABLE clean_patients AS
SELECT source_row,
       business_id AS payment_id,
       clean_department AS department,
       clean_date AS payment_date,
       amount_cents
FROM classified
WHERE disposition = 'Accepted';


DROP TABLE IF EXISTS payment_summary; -- 8

CREATE TABLE payment_summary AS
SELECT department,
       COUNT(*) AS payment_count,
       SUM(amount_cents) AS total_cents
FROM clean_patients
GROUP BY department;
