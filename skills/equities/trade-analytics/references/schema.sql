-- ClickHouse DDL for the equities trade database.
-- This file is reference documentation — the actual tables are managed by infra.
-- Skill authors can read this to understand the exact types and engine settings.

CREATE TABLE IF NOT EXISTS trades
(
    trade_id        String,
    order_id        String,
    trade_date      Date,
    trade_time      DateTime64(3),
    symbol          LowCardinality(String),
    side            Enum8('buy' = 1, 'sell' = 2, 'short_sell' = 3),
    qty             Int64,
    price           Float64,
    order_qty       Int64,
    algo            LowCardinality(String),
    trader          LowCardinality(String),
    desk            LowCardinality(String),
    broker          LowCardinality(String),
    venue           LowCardinality(String),
    is_dark         Bool DEFAULT false,
    client_order_id String DEFAULT '',
    tags            Array(String) DEFAULT []
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(trade_date)
ORDER BY (trade_date, symbol, trade_time)
SETTINGS index_granularity = 8192;


CREATE TABLE IF NOT EXISTS market_data_daily
(
    symbol   LowCardinality(String),
    date     Date,
    open     Float64,
    high     Float64,
    low      Float64,
    close    Float64,
    vwap     Float64,
    volume   Int64,
    adv_20d  Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (date, symbol);


CREATE TABLE IF NOT EXISTS market_data_intraday
(
    symbol   LowCardinality(String),
    bar_time DateTime64(3),
    open     Float64,
    close    Float64,
    high     Float64,
    low      Float64,
    volume   Int64,
    vwap     Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(toDate(bar_time))
ORDER BY (toDate(bar_time), symbol, bar_time)
TTL toDate(bar_time) + INTERVAL 90 DAY;
