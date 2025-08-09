-- Template SQL; formatted by run_etl.py / etl.load with:
-- .format(raw_table=..., strat_view=...)
DROP VIEW IF EXISTS {strat_view};

CREATE VIEW {strat_view} AS
WITH base AS (
    SELECT
        date,
        symbol,
        open,
        high,
        low,
        close,
        adj_close,
        volume,
        LAG(high) OVER (PARTITION BY symbol ORDER BY date) AS prev_high,
        LAG(low)  OVER (PARTITION BY symbol ORDER BY date) AS prev_low
    FROM {raw_table}
)
SELECT
    date,
    symbol,
    open,
    high,
    low,
    close,
    adj_close,
    volume,
    CASE
        -- First row: no previous values
        WHEN prev_high IS NULL OR prev_low IS NULL THEN '1'
        -- Check '3' (both outside) first
        WHEN high > prev_high AND low < prev_low THEN '3'
        -- Then '2u' (higher high, low not below prev_low)
        WHEN high > prev_high AND low >= prev_low THEN '2u'
        -- Then '2d' (lower low, high not above prev_high)
        WHEN high <= prev_high AND low < prev_low THEN '2d'
        -- Else inside bar
        ELSE '1'
    END AS label
FROM base
ORDER BY date;