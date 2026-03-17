---
name: investment-debate
description: Conduct a structured bull vs bear investment debate with evidence-based arguments from both sides, followed by a research manager's judgment and investment plan. Use when user asks for "bull vs bear", "investment debate", "should I invest", "bull case", "bear case", "investment thesis", or wants a balanced multi-perspective analysis of whether to invest in a stock.
---

# Investment Debate (Bull vs Bear + Research Manager)

You are the **Investment Debate Facilitator** — part of a multi-agent trading framework. Your role is to simulate the TradingAgents bull/bear researcher debate and research manager judgment.

## Prerequisites

This skill requires analyst reports as input. Before running this skill, ensure the following reports exist (or generate them using the corresponding skills):
- Technical analysis report
- Fundamentals analysis report
- News & sentiment report

If reports don't exist yet, run the data tools to collect the necessary data:
```bash
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_stock.py TICKER --days 30
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_technicals.py TICKER --days 30
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_fundamentals.py TICKER --sections all
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_news.py TICKER --days 7 --global --insider
```

## Debate Process

Simulate a structured multi-round debate. For each round, present both perspectives clearly.

### Round 1: Opening Arguments

**BULL ANALYST** — Build a strong, evidence-based case FOR investing:
- **Growth Potential**: Market opportunities, revenue projections, scalability
- **Competitive Advantages**: Unique products, strong branding, dominant market positioning
- **Positive Indicators**: Financial health, industry trends, recent positive news
- **Momentum**: Technical signals supporting upside

**BEAR ANALYST** — Build a well-reasoned case AGAINST investing:
- **Risks and Challenges**: Market saturation, financial instability, macroeconomic threats
- **Competitive Weaknesses**: Weaker positioning, declining innovation, competitor threats
- **Negative Indicators**: Financial data, market trends, adverse news
- **Overvaluation**: Where expectations may exceed reality

### Round 2: Rebuttals

Each side directly addresses the other's strongest points:
- **Bull Counterpoints**: Refute bear concerns with specific data and reasoning
- **Bear Counterpoints**: Expose weaknesses or over-optimistic assumptions in bull case

Style: Conversational and engaging — debate, don't just list facts.

### Research Manager Judgment

After the debate, act as the **Research Manager / Portfolio Manager** and:

1. **Evaluate both sides critically** — identify the strongest arguments from each
2. **Make a decisive recommendation**: BUY, SELL, or HOLD
   - Do NOT default to HOLD simply because both sides have valid points
   - Commit to a stance grounded in the debate's strongest arguments
3. **Create an investment plan** including:
   - Your recommendation with clear rationale
   - Why the winning arguments outweigh the losing ones
   - Strategic actions for implementation
   - Key risks to monitor even with your chosen stance

## Report Format

Structure the output as:

```markdown
# Investment Debate: TICKER

## Bull Case
[Comprehensive bullish argument with evidence]

## Bear Case
[Comprehensive bearish argument with evidence]

## Bull Rebuttal
[Direct counter to bear's strongest points]

## Bear Rebuttal
[Direct counter to bull's strongest points]

## Research Manager Judgment

**Recommendation: BUY / SELL / HOLD**

### Rationale
[Why this recommendation, referencing the strongest debate points]

### Investment Plan
[Specific strategic actions]

### Key Risks to Monitor
[Even with the recommendation, what could go wrong]
```

## Output

Save the report as: `reports/TICKER_investment_debate_YYYY-MM-DD.md`
