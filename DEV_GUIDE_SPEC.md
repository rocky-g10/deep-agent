# Developer Quick-Start Guide Spec

## Task
Write `docs/DEVELOPER_GUIDE.md` — a practical quick-start guide for agent/tenant developers who want to build agents using the Deep Agent framework.

## Audience
Developers at business desks (Equities, Risk, etc.) who want to create agents with custom skills. They know Python but NOT the framework internals.

## Tone
Practical, concise, copy-paste-ready. Not a reference manual — a "get running in 15 minutes" guide.

## Structure

### 1. Prerequisites
- Python 3.12+, Docker, Git
- Clone the repo
- Install dependencies

### 2. Project Structure Overview
- Brief tour of the repo layout — what's where, what they should NOT touch (framework core) vs what they own (skills/)

### 3. Creating Your First Skill
Walk through creating a complete skill from scratch. Use a CONCRETE example — e.g., a "Portfolio Risk Report" skill that:
- Has proper YAML frontmatter
- Follows the Anthropic AgentSkills directory structure (SKILL.md, scripts/, references/, assets/)
- Includes a `scripts/requirements.txt` for its dependencies

### 4. Three Integration Patterns (ONE skill that shows ALL three)
Create a single concrete example skill that demonstrates all three patterns together:

**Pattern A: Custom Code Import**
- Skill bundles a Python module in `scripts/` (e.g., `scripts/risk_calc.py` with VaR calculation)
- Sandbox code does `from risk_calc import calculate_var`

**Pattern B: Database Connection with Code-Generated Query**
- Skill references a resource alias (e.g., `kdb-trading`)
- Agent generates Python code that connects via `os.environ["DB_HOST"]` etc.
- Show that ANY database works — the example uses KDB+ to show it's not just ClickHouse

**Pattern C: MCP Tool Call**
- Skill's `allowed-tools` includes an MCP tool (e.g., `get_market_data`)
- Agent calls the MCP tool within the workflow

### 5. Configuring Your Agent
- How to create an agent config with skill bindings
- How to set up resource aliases for your data sources
- How to configure MCP servers

### 6. Running Locally
- `python scripts/run_dev.py` or equivalent
- Send a test query
- See the result

### 7. Testing Your Skill
- How to validate your skill works end-to-end
- Common debugging tips

### 8. Deploying to Production
- PR your skill to the skills repo
- CI validates frontmatter + structure
- Merged → auto-deployed

## Key Rules
- Use KDB+ (not ClickHouse) as the database example to reinforce that the framework is DB-agnostic
- The example must be COMPLETE and copy-pasteable — a developer should be able to follow it verbatim
- Reference the PRD for deeper details but don't duplicate PRD content
- Keep it under 2000 words — developers don't read long docs
- Include the actual file contents for the example skill (SKILL.md, scripts/*.py, scripts/requirements.txt)
