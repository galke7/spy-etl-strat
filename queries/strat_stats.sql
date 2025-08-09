-- Count of days per label
SELECT label, COUNT(*) AS cnt
FROM spy_prices_strat
GROUP BY label
ORDER BY cnt DESC;

-- Top 10 daily % gains overall (requires previous close)
WITH c AS (
  SELECT
    date,
    label,
    close,
    LAG(close) OVER (ORDER BY date) AS prev_close
  FROM spy_prices_strat
)
SELECT
  date,
  label,
  ROUND( (close / prev_close - 1.0) * 100.0, 2 ) AS pct_change
FROM c
WHERE prev_close IS NOT NULL
ORDER BY pct_change DESC
LIMIT 10;

-- Top 3 daily % gains per label
WITH c AS (
  SELECT
    date,
    label,
    close,
    LAG(close) OVER (ORDER BY date) AS prev_close
  FROM spy_prices_strat
),
r AS (
  SELECT
    *,
    (close / prev_close - 1.0) * 100.0 AS pct_change,
    ROW_NUMBER() OVER (PARTITION BY label ORDER BY (close / prev_close - 1.0) DESC) AS rn
  FROM c
  WHERE prev_close IS NOT NULL
)
SELECT date, label, ROUND(pct_change, 2) AS pct_change
FROM r
WHERE rn <= 3
ORDER BY label, pct_change DESC;