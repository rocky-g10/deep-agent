# Sample Queries for Trade Analytics

These can be used as test cases or quick-start references.

## Daily Desk Summary
```sql
SELECT
    desk,
    uniqExact(order_id) AS orders,
    sum(qty)            AS shares,
    sum(qty * price)    AS notional,
    avg(qty)            AS avg_fill_size
FROM trades
WHERE trade_date = today()
GROUP BY desk
ORDER BY notional DESC
```

## Broker Scorecard (slippage by broker, last 30 days)
```sql
SELECT
    t.broker,
    count()                                        AS fills,
    sum(t.qty * t.price) / sum(t.qty)              AS exec_vwap,
    avg(md.vwap)                                   AS avg_mkt_vwap,
    avg(
        if(t.side = 'buy', 1, -1)
        * (t.price - md.vwap) / md.vwap * 10000
    )                                              AS avg_slippage_bps
FROM trades t
JOIN market_data_daily md ON md.symbol = t.symbol AND md.date = t.trade_date
WHERE t.trade_date >= today() - 30
GROUP BY t.broker
ORDER BY avg_slippage_bps ASC
```

## Dark Pool Usage Trend (daily, last 2 weeks)
```sql
SELECT
    trade_date,
    sum(if(is_dark, qty, 0))                  AS dark_volume,
    sum(qty)                                   AS total_volume,
    dark_volume / total_volume * 100           AS dark_pct
FROM trades
WHERE trade_date >= today() - 14
GROUP BY trade_date
ORDER BY trade_date
```

## Trader Leaderboard (fill rate + slippage)
```sql
SELECT
    t.trader,
    uniqExact(t.order_id)                                   AS orders,
    avg(fill_rates.fill_rate)                                AS avg_fill_rate_pct,
    avg(
        if(t.side = 'buy', 1, -1)
        * (t.price - md.vwap) / md.vwap * 10000
    )                                                        AS avg_slippage_bps
FROM trades t
JOIN market_data_daily md ON md.symbol = t.symbol AND md.date = t.trade_date
JOIN (
    SELECT order_id, sum(qty) / max(order_qty) * 100 AS fill_rate
    FROM trades
    WHERE trade_date >= today() - 30
    GROUP BY order_id
) fill_rates ON fill_rates.order_id = t.order_id
WHERE t.trade_date >= today() - 30
GROUP BY t.trader
ORDER BY avg_slippage_bps ASC
```

## Algo Performance Comparison
```sql
SELECT
    t.algo,
    count()                                        AS fills,
    sum(t.qty)                                     AS shares,
    sum(t.qty * t.price)                           AS notional,
    sum(t.qty * t.price) / sum(t.qty)              AS exec_vwap,
    avg(
        if(t.side = 'buy', 1, -1)
        * (t.price - md.vwap) / md.vwap * 10000
    )                                              AS avg_slippage_bps,
    avg(t.qty) / avg(md.adv_20d) * 100            AS avg_participation_pct
FROM trades t
JOIN market_data_daily md ON md.symbol = t.symbol AND md.date = t.trade_date
WHERE t.trade_date >= today() - 7
GROUP BY t.algo
ORDER BY avg_slippage_bps ASC
```
