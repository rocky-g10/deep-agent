---
name: trade-analytics
description: >
  Chat with an equities trade database. Translates natural-language questions
  into ClickHouse SQL, executes queries, and returns formatted results with
  optional charts. Understands the full schema — raw columns, enums, and
  derived measures like VWAP, slippage, fill rate, and participation rate.
version: "1.0.0"
tags:
  - equities
  - trades
  - analytics
  - clickhouse
  - sql
  - database
  - chat
allowed-tools:
  - execute_code
inputs:
  - name: question
    type: string
    description: Natural-language question about trade data
  - name: date_range
    type: string
    description: "Optional date filter, e.g. 'last 7 days', '2026-03-01 to 2026-03-15' (default: today)"
  - name: chart
    type: boolean
    description: "If true, generate a matplotlib chart saved to /output/chart.png"
quality:
  timeout: 60
  max-retries: 1
  accuracy: "SQL validated against ClickHouse 24.x syntax"
  validation: "Output must include the SQL query used and a human-readable summary of results."
---

# Trade Analytics — Chat with the Trade Database

## Purpose

Use this skill when the user asks questions about trade executions, order flow,
fill quality, desk activity, or any data in the equities trade database.

Examples of questions this skill handles:
- "What was our VWAP slippage on AAPL today?"
- "Show me the top 10 symbols by notional traded this week"
- "How does Jane's fill rate compare to the desk average?"
- "Plot hourly participation rate for MSFT on March 14"
- "Which algo had the worst slippage last month?"

---

## Database Schema

The database is **ClickHouse**. Connect using env vars:

| Env Var    | Description               |
|------------|---------------------------|
| `DB_HOST`  | ClickHouse host           |
| `DB_PORT`  | ClickHouse native port    |
| `DB_USER`  | Read-only username        |
| `DB_PASS`  | Password (may be empty)   |
| `DB_NAME`  | Database name             |

### Table: `trades`

The primary fact table. One row per execution (fill).

| Column            | Type          | Description                                          |
|-------------------|---------------|------------------------------------------------------|
| `trade_id`        | `String`      | Unique execution ID (UUID)                           |
| `order_id`        | `String`      | Parent order ID — groups partial fills               |
| `trade_date`      | `Date`        | Trade date (partition key)                           |
| `trade_time`      | `DateTime64(3)` | Execution timestamp (millisecond precision)        |
| `symbol`          | `LowCardinality(String)` | Ticker symbol (e.g. `AAPL`)               |
| `side`            | `Enum8('buy'=1, 'sell'=2, 'short_sell'=3)` | Order side       |
| `qty`             | `Int64`       | Filled quantity (shares)                             |
| `price`           | `Float64`     | Execution price                                      |
| `order_qty`       | `Int64`       | Total order quantity (for fill-rate calculations)    |
| `algo`            | `LowCardinality(String)` | Algo/strategy name (e.g. `TWAP`, `VWAP`, `IS`, `DMA`) |
| `trader`          | `LowCardinality(String)` | Trader ID / desk login                     |
| `desk`            | `LowCardinality(String)` | Trading desk (e.g. `eq-cash`, `eq-derivs`) |
| `broker`          | `LowCardinality(String)` | Executing broker                           |
| `venue`           | `LowCardinality(String)` | Execution venue (e.g. `XNYS`, `ARCX`, `dark`) |
| `is_dark`         | `Bool`        | True if executed in a dark pool                      |
| `client_order_id` | `String`      | Client-assigned order reference                      |
| `tags`            | `Array(String)` | Free-form tags (e.g. `['rebalance', 'index-add']`) |

### Table: `market_data_daily`

End-of-day reference data. Used for benchmark calculations.

| Column      | Type          | Description                        |
|-------------|---------------|------------------------------------|
| `symbol`    | `LowCardinality(String)` | Ticker symbol            |
| `date`      | `Date`        | Trading date                       |
| `open`      | `Float64`     | Opening price                      |
| `high`      | `Float64`     | Day high                           |
| `low`       | `Float64`     | Day low                            |
| `close`     | `Float64`     | Closing price                      |
| `vwap`      | `Float64`     | Consolidated VWAP (full day)       |
| `volume`    | `Int64`       | Total consolidated volume          |
| `adv_20d`   | `Float64`     | 20-day average daily volume        |

### Table: `market_data_intraday`

1-minute bars for intraday benchmarking.

| Column      | Type            | Description                     |
|-------------|-----------------|---------------------------------|
| `symbol`    | `LowCardinality(String)` | Ticker symbol         |
| `bar_time`  | `DateTime64(3)` | Bar start time                  |
| `open`      | `Float64`       | Bar open                        |
| `close`     | `Float64`       | Bar close                       |
| `high`      | `Float64`       | Bar high                        |
| `low`       | `Float64`       | Bar low                         |
| `volume`    | `Int64`         | Bar volume                      |
| `vwap`      | `Float64`       | Bar VWAP                        |

---

## Derived Measures

These are **not stored** — compute them from the raw columns above. Always use
these definitions so results are consistent across queries.

### Notional Value
```sql
qty * price AS notional
```
Dollar value of an execution.

### VWAP (our executions)
```sql
sum(qty * price) / sum(qty) AS exec_vwap
```
Volume-weighted average price of our fills. Group by `symbol`, `order_id`, or any dimension.

### VWAP Slippage (bps)
```sql
(exec_vwap - mkt.vwap) / mkt.vwap * 10000 AS slippage_bps
```
How our VWAP compares to the market VWAP benchmark. **Positive = we paid more (worse for buys).**
Flip sign for sells: multiply by `if(side = 'buy', 1, -1)`.

```sql
-- Full formula (side-aware)
if(side = 'buy', 1, -1) * (exec_vwap - mkt.vwap) / mkt.vwap * 10000 AS slippage_bps
```

### Implementation Shortfall (bps)
```sql
if(side = 'buy', 1, -1) * (exec_vwap - arrival_price) / arrival_price * 10000 AS is_bps
```
Where `arrival_price` is the market price at the time the order was placed. Use the
`market_data_intraday` bar closest to the first fill's `trade_time` for the order.

### Fill Rate (%)
```sql
sum(qty) / max(order_qty) * 100 AS fill_rate_pct
```
Percentage of the parent order that was filled. Group by `order_id`.

### Participation Rate (%)
```sql
sum(t.qty) / md.volume * 100 AS participation_rate_pct
```
Our volume as a share of total market volume. Join `trades` with `market_data_daily`
on `symbol` + `trade_date = date`. Can also compute intraday by joining on minute bars.

### Dark Pool Ratio (%)
```sql
sum(if(is_dark, qty, 0)) / sum(qty) * 100 AS dark_pct
```
Share of our volume executed in dark pools.

### Average Trade Size
```sql
avg(qty) AS avg_trade_size
```

### Order Count
```sql
uniqExact(order_id) AS order_count
```
Distinct parent orders.

### Venue Concentration
```sql
sum(qty) / (SELECT sum(qty) FROM trades WHERE ...) * 100 AS venue_pct
```
Group by `venue` to see venue distribution.

---

## Instructions

1. **Parse the question** — Identify the metric(s), symbol(s), date range, grouping, and
   whether a chart is requested.

2. **Write ClickHouse SQL** — Use the schema and derived measures above. Always:
   - Filter by `trade_date` (it's the partition key — queries without it scan the full table).
   - Use `LowCardinality` columns in `WHERE` and `GROUP BY` freely — they're optimized.
   - Prefer `sum(qty * price) / sum(qty)` over subqueries for VWAP.
   - Use `if(side = 'buy', 1, -1)` when computing directional slippage.
   - Quote identifiers only if they collide with reserved words.

3. **Execute via `execute_code`** — Write Python that:
   - Connects using `clickhouse_connect` + env vars
   - Runs the query
   - Formats results with `tabulate` or pandas
   - Optionally generates a chart with matplotlib → `/output/chart.png`

4. **Explain the result** — Always:
   - Show the SQL you ran (in a code block)
   - Summarize the key findings in plain English
   - Flag anything unusual (e.g., high slippage, low fill rates, concentration risk)

---

## Example Queries

### "Top 10 symbols by notional this week"
```sql
SELECT
    symbol,
    sum(qty * price) AS notional,
    uniqExact(order_id) AS orders,
    sum(qty) AS total_shares
FROM trades
WHERE trade_date >= today() - 7
GROUP BY symbol
ORDER BY notional DESC
LIMIT 10
```

### "VWAP slippage by algo for AAPL today"
```sql
SELECT
    t.algo,
    sum(t.qty * t.price) / sum(t.qty) AS exec_vwap,
    md.vwap AS mkt_vwap,
    (sum(t.qty * t.price) / sum(t.qty) - md.vwap) / md.vwap * 10000 AS slippage_bps,
    sum(t.qty) AS shares
FROM trades t
JOIN market_data_daily md ON md.symbol = t.symbol AND md.date = t.trade_date
WHERE t.symbol = 'AAPL' AND t.trade_date = today()
GROUP BY t.algo, md.vwap
ORDER BY slippage_bps DESC
```

### "Hourly participation rate for MSFT on 2026-03-14"
```sql
SELECT
    toStartOfHour(t.trade_time) AS hour,
    sum(t.qty) AS our_volume,
    sum(md.volume) AS mkt_volume,
    sum(t.qty) / sum(md.volume) * 100 AS participation_pct
FROM trades t
JOIN market_data_intraday md
    ON md.symbol = t.symbol
    AND toStartOfMinute(md.bar_time) = toStartOfMinute(t.trade_time)
WHERE t.symbol = 'MSFT' AND t.trade_date = '2026-03-14'
GROUP BY hour
ORDER BY hour
```

---

## Code Template

```python
import os
import clickhouse_connect
import pandas as pd
from tabulate import tabulate

client = clickhouse_connect.get_client(
    host=os.environ["DB_HOST"],
    port=int(os.environ["DB_PORT"]),
    username=os.environ.get("DB_USER", "default"),
    password=os.environ.get("DB_PASS", ""),
    database=os.environ.get("DB_NAME", "default"),
)

sql = """
<YOUR QUERY HERE>
"""

result = client.query(sql)
df = pd.DataFrame(result.result_rows, columns=result.column_names)

print(tabulate(df, headers="keys", tablefmt="github", floatfmt=".2f", showindex=False))

# Optional chart
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(10, 5))
# ... plot logic ...
fig.savefig("/output/chart.png", dpi=150, bbox_inches="tight")
print("\nChart saved to /output/chart.png")
```
