---
name: investor-personas
description: >
  Analyze a stock through the lenses of legendary investors: Warren Buffett,
  Charlie Munger, Benjamin Graham, Aswath Damodaran, Cathie Wood, Michael Burry,
  and Stanley Druckenmiller. Each persona applies their unique methodology
  and scoring criteria. Use when user asks for "investor perspectives",
  "what would Buffett think", "multi-persona analysis", "legendary investor
  analysis", or wants diverse viewpoints on a stock.
---

# Investor Personas Analysis

Analyze a stock through multiple legendary investor frameworks. Each persona has specific quantitative criteria and thresholds. The goal is to surface where these investors would **agree** (high conviction) or **disagree** (areas of uncertainty).

## Data Collection

Gather comprehensive financial data before running persona analyses:

```bash
# Fundamentals via Financial Datasets API (preferred)
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint key-ratios
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint financials --period annual --limit 10
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint analyst-estimates
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint company-facts

# Or via yfinance fallback
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_fundamentals.py TICKER --sections all --freq annual

# Price & technicals
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_stock.py TICKER --days 365

# News & insider
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_news.py TICKER --days 30 --insider

# Advanced computations
python ${CLAUDE_PLUGIN_ROOT}/tools/calculate_technicals.py TICKER --days 180
python ${CLAUDE_PLUGIN_ROOT}/tools/calculate_valuation.py TICKER --market-cap MC --net-income NI --depreciation D --capex C --working-capital-change WC --earnings-growth G --fcf-history "..." --revenue-growth RG --enterprise-value EV --ev-ebitda-ratio R --price-to-book PB --total-debt TD --cash CASH
```

## Persona Analyses

For each persona, evaluate the stock against their specific criteria and assign a signal (bullish/bearish/neutral) with confidence (0-100%) and reasoning.

### 1. Warren Buffett — Value & Quality

**Philosophy:** Wonderful business at a fair price. Competitive moat, quality management, margin of safety.

**Scoring criteria:**
- **Fundamentals** (0-7 pts): ROE > 15% (+2), D/E < 0.5 (+2), operating margin > 15% (+2), current ratio > 1.5 (+1)
- **Earnings consistency** (0-3 pts): Earnings growth across all periods (+3), most periods (+2)
- **Competitive moat** (0-5 pts): ROE consistently >15% in 80%+ periods (+2), stable/improving margins >20% (+1), efficient asset utilization (+1), high performance stability (+1)
- **Management quality** (0-2 pts): Share buybacks (+1), dividend track record (+1)
- **Pricing power** (0-5 pts): Expanding gross margins (+3), high avg gross margin >50% (+2)
- **Intrinsic value**: 3-stage DCF (5yr high growth capped 8%, 5yr transition, terminal 2.5%), 15% additional MoS haircut

**Signal rules:**
- Bullish: Strong business (high score) AND margin of safety > 0
- Bearish: Poor business OR clearly overvalued
- Neutral: Good business but no margin of safety, or mixed signals

### 2. Charlie Munger — Quality & Predictability

**Philosophy:** High standards. Quality over bargains. Predictable businesses with pricing power.

**Scoring (weighted: 35% moat + 25% management + 25% predictability + 15% valuation):**
- **Moat strength** (0-10): ROIC consistently >15% (+3), improving gross margins (+2), low capex/revenue <5% (+2), R&D investment (+1), goodwill/intangibles (+1)
- **Management quality** (0-10): FCF/NI ratio >1.1 (+3), conservative D/E <0.3 (+3), prudent cash management (+2), insider buying ratio >0.7 (+2), reducing share count (+2)
- **Business predictability** (0-10): Steady revenue growth with low volatility (+3), consistently positive operating income (+3), stable margins (+2), reliable FCF generation (+2)
- **Valuation** (0-10): FCF yield >8% (+4), margin of safety >30% to reasonable value (15x FCF) (+3), growing FCF trend (+3)

**Signal rules:** Bullish if weighted score >= 7.5; Bearish if <= 5.5

### 3. Benjamin Graham — Deep Value & Safety

**Philosophy:** Margin of safety. Net-net, Graham Number, earnings stability, conservative balance sheet.

**Key metrics:**
- **Earnings stability** (0-4 pts): Positive EPS in all periods (+3), EPS growth from earliest to latest (+1)
- **Financial strength** (0-5 pts): Current ratio >= 2.0 (+2), debt/assets < 0.5 (+2), dividend track record (+1)
- **Valuation** (0-7 pts): NCAV > market cap (+4), NCAV/share >= 2/3 price (+2), Graham Number margin of safety >50% (+3) or >20% (+1)

**Graham Number:** √(22.5 × EPS × Book Value per Share)
**Net-Net:** Current Assets − Total Liabilities vs. Market Cap

**Signal rules:** Bullish if score >= 70% of max; Bearish if <= 30%

### 4. Aswath Damodaran — Rigorous Valuation

**Philosophy:** Story → Numbers → Value. CAPM, FCFF DCF, risk assessment, relative valuation checks.

**Scoring:**
- **Growth & Reinvestment** (0-4): Revenue CAGR >8% (+2), positive FCFF growth (+1), ROIC >10% (+1)
- **Risk Profile** (0-3): Beta <1.3 (+1), D/E <1 (+1), interest coverage >3x (+1)
- **Relative Valuation** (0-1): TTM P/E < 70% of 5-yr median (+1)

**DCF methodology:** FCFF DCF with fading growth (revenue CAGR capped 12%, fading to 2.5% terminal over 10 years). Discount at cost of equity via CAPM (4% risk-free + β × 5% ERP).

**Signal rules:** Bullish if margin of safety >= 25%; Bearish if <= -25%

### 5. Cathie Wood — Disruptive Innovation

**Philosophy:** Breakthrough technology, exponential growth, massive TAM. Willing to tolerate volatility.

**Scoring:**
- **Disruptive potential** (0-5, normalized): Revenue growth acceleration (+2), exceptional growth >100% (+3), expanding gross margins (+2), high gross margin >50% (+2), operating leverage (+2), R&D intensity >15% (+3)
- **Innovation growth** (0-5, normalized): Growing R&D investment (+3), increasing R&D intensity (+2), strong FCF growth (+3), improving operating margin (+3), growth infrastructure investment (+2), reinvestment focus over dividends (+2)
- **Valuation** (0-3): High-growth DCF (20% growth, 15% discount, 25x terminal) with >50% MoS (+3)

**Signal rules:** Bullish if score >= 70% of max; Bearish if <= 30%

### 6. Michael Burry — Deep Value & Contrarian

**Philosophy:** Deep value, contrarian. Hate the consensus, love the numbers. FCF yield, EV/EBIT, fortress balance sheet.

**Scoring:**
- **Value** (0-6): FCF yield >=15% (+4), >=12% (+3), >=8% (+2); EV/EBIT <6 (+2), <10 (+1)
- **Balance sheet** (0-3): D/E <0.5 (+2), net cash position (+1)
- **Insider activity** (0-2): Net insider buying with high ratio (+2), any net buying (+1)
- **Contrarian sentiment** (0-1): >=5 negative headlines (+1) — the more hated, the better if fundamentals hold

**Signal rules:** Bullish if score >= 70% of max; Bearish if <= 30%

### 7. Stanley Druckenmiller — Momentum & Asymmetric Risk-Reward

**Philosophy:** Asymmetric bets. Growth + momentum + sentiment. Aggressive when conviction is high.

**Scoring (weighted: 35% growth/momentum, 20% risk-reward, 20% valuation, 15% sentiment, 10% insider):**
- **Growth & Momentum** (0-10): Revenue CAGR >8% (+3), EPS CAGR >8% (+3), price momentum >50% (+3)
- **Risk-Reward** (0-10): D/E <0.3 (+3), low price volatility stdev <1% (+3)
- **Valuation** (0-10): P/E <15 (+2), P/FCF <15 (+2), EV/EBIT <15 (+2), EV/EBITDA <10 (+2)
- **Sentiment** (0-10): Mostly positive headlines (+8), some negative (+6)
- **Insider activity** (0-10): Heavy buying ratio >70% (+8), moderate (+6)

**Signal rules:** Bullish if weighted score >= 7.5; Bearish if <= 4.5

## Synthesis

After running all persona analyses, present:

1. **Consensus Matrix**: Table showing each persona's signal, confidence, and key reasoning
2. **Agreement Analysis**: Where do personas agree? (high conviction signal)
3. **Disagreement Analysis**: Where do they disagree? (growth vs value tension, etc.)
4. **Cross-Persona Insights**: What does the disagreement pattern tell us?
   - All value investors bullish + growth bearish = mature value play
   - All growth bullish + value bearish = momentum/innovation play
   - Universal bullish = strong conviction across frameworks
   - Universal bearish = avoid
5. **Composite Signal**: Weighted average across all personas

## Output

Save the report as: `reports/TICKER_investor_personas_YYYY-MM-DD.md`
