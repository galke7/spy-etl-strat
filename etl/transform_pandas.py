import pandas as pd


def label_strat(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a DataFrame with columns:
      date, symbol, open, high, low, close, adj_close, volume
    return a new DataFrame with the same columns plus 'label' using The Strat rules:

    prev_high = LAG(high), prev_low = LAG(low) partitioned by symbol ordered by date.
    - If prev_high is NULL (first row): '1'
    - If high > prev_high AND low < prev_low: '3'
    - If high > prev_high AND low >= prev_low: '2u'
    - If high <= prev_high AND low < prev_low: '2d'
    - Else: '1'
    """
    df = df.copy()
    # Ensure sorted order per symbol/date
    df.sort_values(["symbol", "date"], inplace=True)
    df["prev_high"] = df.groupby("symbol")["high"].shift(1)
    df["prev_low"] = df.groupby("symbol")["low"].shift(1)

    # Initialize labels as '1'
    label = pd.Series(["1"] * len(df), index=df.index)

    # '3' first
    cond_3 = (df["prev_high"].notna()) & (df["prev_low"].notna()) & (df["high"] > df["prev_high"]) & (df["low"] < df["prev_low"])
    label[cond_3] = "3"

    # '2u'
    cond_2u = (df["prev_high"].notna()) & (df["high"] > df["prev_high"]) & (df["low"] >= df["prev_low"])
    label[cond_2u & ~cond_3] = "2u"

    # '2d'
    cond_2d = (df["prev_low"].notna()) & (df["low"] < df["prev_low"]) & (df["high"] <= df["prev_high"])
    label[cond_2d & ~cond_3] = "2d"

    df["label"] = label.astype(str)
    df.drop(columns=["prev_high", "prev_low"], inplace=True)
    return df