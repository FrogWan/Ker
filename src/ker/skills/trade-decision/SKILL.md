---
name: trade-decision
description: Run the full TradingAgents pipeline for a stock — technical analysis, fundamentals, news/sentiment, bull/bear debate, trader decision, risk assessment — to produce a final BUY/SELL/HOLD recommendation with comprehensive reasoning. Use when user asks for "trade decision", "full analysis", "analyze [ticker]", "should I buy/sell [ticker]", "trading recommendation", or wants an end-to-end multi-agent trading analysis.
---

# Full Trade Decision Pipeline

You are the **Trading Agents Orchestrator** — running the complete multi-agent analysis pipeline to produce a final BUY/SELL/HOLD recommendation. This mirrors the TradingAgents (TauricResearch) framework.

## Pipeline Overview

```
Analysts (parallel) → Bull/Bear Debate → Trader Decision → Risk Debate → Final Decision
     │                      │                  │                │              │
  Technical            Bull argues         Trader makes    3-way risk      Risk Judge
  Fundamentals         Bear argues         trade plan      debate          renders
  News/Sentiment       Manager judges                                      final verdict
  [DCF Valuation]
  [X/Twitter Sentiment]
```

## Investment Philosophy

Ground your analysis in these principles (adapted from Buffett/Munger):

- **Price vs. Value**: Always try to understand what something is actually worth before forming a view on whether it's cheap or expensive. The market is a voting machine in the short run and a weighing machine in the long run.
- **Invert, Always Invert**: Before asking "why would this investment work," ask "what would make it fail." Avoiding stupidity is more reliable than seeking brilliance.
- **Circle of Competence**: Say "I don't know" rather than pretend to understand a business you haven't studied. Intellectual honesty is the foundation.
- **Margin of Safety**: The future is uncertain. The numbers should leave room for being wrong.
- **Quality Over Bargains**: The best investment is a wonderful business at a fair price, not a mediocre business at a bargain price. Quality compounds.
- **Evidence Over Doctrine**: When evidence conflicts with doctrine, follow the evidence. Consensus is data, not gospel.
- **Accuracy Over Comfort**: Deliver uncomfortable truths rather than reassuring guesses. Flag value traps clearly.

Apply these principles throughout the pipeline — especially in the debate and risk assessment phases.

## Step 1: Data Collection

Run all data-fetching tools. Execute these in parallel where possible:

```bash
# Price & technical data
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_stock.py TICKER --days 30
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_technicals.py TICKER --indicators rsi,macd,macds,macdh,boll,boll_ub,boll_lb,atr --days 30

# Advanced technical strategy signals (optional — 5-strategy ensemble)
python ${CLAUDE_PLUGIN_ROOT}/tools/calculate_technicals.py TICKER --days 180

# Fundamentals
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_fundamentals.py TICKER --sections all

# News & sentiment
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_news.py TICKER --days 7 --global --insider

# X/Twitter sentiment (optional — requires X_BEARER_TOKEN)
python ${CLAUDE_PLUGIN_ROOT}/tools/search_x.py search --query "$TICKER" --sort likes --limit 15 --since 7d
```

## Step 2: Analyst Reports

Using the collected data, write four analyst reports:

### 2a. Technical/Market Report
Analyze price action, moving averages, MACD, RSI, Bollinger Bands, ATR, volume indicators. Identify trend direction, momentum, support/resistance, and trading patterns.

### 2b. Fundamentals Report
Evaluate valuation ratios, profitability, balance sheet health, cash flow quality, income trends, and red flags.

### 2c. News & Sentiment Report
Assess company news flow, social media sentiment, macro environment, sector trends, and insider activity. If `X_BEARER_TOKEN` is available, incorporate X/Twitter sentiment from `search_x.py` into this report.

### 2d. DCF Valuation (Optional — Individual Equities)
For individual equities (not ETFs/indices), run the **dcf-valuation** skill to estimate intrinsic value:

```bash
# Gather DCF inputs via Financial Datasets API (or yfinance fallback)
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint cash-flow --period annual --limit 5
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint key-ratios
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint balance-sheets --period annual --limit 1
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint price

# Run DCF calculator with gathered inputs
python ${CLAUDE_PLUGIN_ROOT}/tools/calculate_dcf.py TICKER \
  --fcf-history "..." --growth-rate X --wacc Y --terminal-growth 0.025 \
  --total-debt D --cash C --shares-outstanding S --current-price P --current-ev EV
```

Incorporate the fair value estimate and sensitivity range into the investment debate as an intrinsic value anchor.

### 2e. Investor Persona Analysis (Optional)
For deeper multi-perspective analysis, run the **investor-personas** skill to evaluate the stock through 7 legendary investor frameworks (Buffett, Munger, Graham, Damodaran, Wood, Burry, Druckenmiller). The consensus matrix helps identify where diverse investment philosophies agree or disagree — high agreement signals stronger conviction.

## Step 3: Investment Debate

### Bull Researcher
Using all analyst reports, make the strongest evidence-based case FOR investing. Focus on growth potential, competitive advantages, positive indicators.

### Bear Researcher
Make the strongest case AGAINST investing. Focus on risks, competitive weaknesses, negative indicators, overvaluation.

### Research Manager Judgment
Evaluate both sides. Make a decisive recommendation (BUY/SELL/HOLD) with a clear investment plan. Do NOT default to HOLD as a compromise.

## Step 4: Trader Decision

Based on the research manager's investment plan and all analyst reports, formulate a specific trading decision:
- Entry/exit strategy
- Position sizing rationale
- Timing considerations
- Key catalysts to watch

End with: **PROPOSED TRADE: BUY / SELL / HOLD**

## Step 5: Risk Debate

### Aggressive Analyst
Champion the trade's upside potential, argue caution costs more than risk.

### Conservative Analyst
Highlight downside scenarios, advocate for asset protection.

### Neutral Analyst
Balance both perspectives, advocate for risk-adjusted approach.

### Risk Manager Final Decision
Evaluate the three-way debate. Render the **final recommendation**:
- Clear BUY / SELL / HOLD decision
- Refined plan with risk parameters (position size, stop-loss, triggers)
- Confidence level

## Final Report Format

```markdown
# Trading Agents Analysis: TICKER
**Date**: YYYY-MM-DD
**Final Decision**: BUY / SELL / HOLD
**Confidence**: High / Medium / Low

---

## Executive Summary
[2-3 sentence summary of the final decision and key reasoning]

## Analyst Reports

### Technical Analysis
[Summary of key technical findings]

### Fundamentals Analysis
[Summary of key fundamental findings]

### News & Sentiment
[Summary of key news/sentiment findings]

## Investment Debate

### Bull Case
[Key bullish arguments]

### Bear Case
[Key bearish arguments]

### Research Manager Verdict
[Decision and rationale]

## Trader's Plan
[Specific trading plan]

## Risk Assessment

### Aggressive View
[Key points]

### Conservative View
[Key points]

### Neutral View
[Key points]

## Final Decision

**Recommendation: BUY / SELL / HOLD**

| Parameter | Value |
|-----------|-------|
| Direction | BUY / SELL / HOLD |
| Confidence | High / Medium / Low |
| Position Size | [suggestion] |
| Stop-Loss | [level] |
| Target | [level] |
| Time Horizon | [short/medium/long] |
| Key Catalyst | [what to watch] |
| Key Risk | [what could go wrong] |

### Rationale
[Detailed reasoning synthesizing all analyses]
```

## Output

Save the full report as: `reports/TICKER_trade_decision_YYYY-MM-DD.md`

## Important Disclaimer

This analysis is for research purposes only. It is not financial, investment, or trading advice. Trading performance depends on many factors including market conditions, timing, data quality, and other non-deterministic variables.
