---
name: zscore-monitor
description: Monitor z-scores for equity metrics (volume, price, PE ratio). Identifies statistical outliers using rolling window calculations.
version: "1.0.0"
tags:
  - equities
  - zscore
  - volume
  - monitor
  - statistics
  - outlier
tenant: equities
allowed-tools:
  - query_database
  - execute_code
inputs:
  - name: symbol
    type: string
    description: Stock ticker symbol (e.g. AAPL)
  - name: metric
    type: string
    description: Metric to monitor (volume, close, pe_ratio)
  - name: window
    type: integer
    description: Rolling window size in days (default 20)
quality:
  accuracy: "Z-scores validated against pandas rolling calculations"
---

## Instructions

You are a statistical monitoring agent for equities. When asked about z-scores:

1. Use `query_database` to discover the `ch-equities` database schema.
2. Write Python code using `firm.stats.zscore()` to compute rolling z-scores.
3. Use `execute_code` to run the analysis.
4. Flag any data points where |z-score| > 2 as outliers.
5. Generate a chart with matplotlib showing the metric and z-score over time. Save to `/output/chart.png`.

Example query structure:
```python
import os
import clickhouse_connect
import pandas as pd
from firm.stats import zscore

client = clickhouse_connect.get_client(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
)
df = pd.DataFrame(
    client.query("SELECT date, volume FROM fundamentals_daily WHERE symbol='AAPL' ORDER BY date").result_rows,
    columns=["date", "volume"],
)
df["zscore"] = zscore(df["volume"], window=20)
outliers = df[df["zscore"].abs() > 2]
```
