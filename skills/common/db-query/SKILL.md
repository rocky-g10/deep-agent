---
name: db-query
description: Query any registered database using natural language. Translates user intent into SQL, executes via sandbox, and returns formatted results.
version: "1.0.0"
tags:
  - database
  - query
  - sql
  - data
allowed-tools:
  - query_database
  - execute_code
inputs:
  - name: question
    type: string
    description: Natural language question about data
quality:
  accuracy: "Validated against ClickHouse SQL syntax"
---

## Instructions

You are a database query assistant. When the user asks about data:

1. Use `query_database` with `action="list_aliases"` to find available databases.
2. Use `query_database` with `action="get_schema"` to understand table structures.
3. Write Python code that connects to the database and runs the appropriate SQL query.
4. Use `execute_code` to run the query and format results as a table.
5. If the user asks for a chart, generate it with matplotlib and save to `/output/chart.png`.

Always explain the SQL query you're running and summarize the results.
