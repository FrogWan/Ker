---
name: dcf-valuation
description: Performs discounted cash flow (DCF) valuation analysis to estimate intrinsic value per share. Triggers when user asks for fair value, intrinsic value, DCF, valuation, "what is X worth", price target, undervalued/overvalued analysis, or wants to compare current price to fundamental value.
---

# DCF Valuation Skill

## Workflow Checklist

Copy and track progress:
```
DCF Analysis Progress:
- [ ] Step 1: Gather financial data
- [ ] Step 2: Calculate FCF growth rate
- [ ] Step 3: Estimate discount rate (WACC)
- [ ] Step 4: Run DCF calculator
- [ ] Step 5: Review validation checks
- [ ] Step 6: Present formatted report
```

## Step 1: Gather Financial Data

Fetch data using `fetch_financial_datasets.py` (primary) with `fetch_fundamentals.py` as yfinance fallback if `FINANCIAL_DATASETS_API_KEY` is not set.

### 1.1 Cash Flow History (5 years)

```bash
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint cash-flow --period annual --limit 5
```

**Extract:** `free_cash_flow`, `net_cash_flow_from_operations`, `capital_expenditure`

**Fallback:** If `free_cash_flow` missing, calculate: `net_cash_flow_from_operations - capital_expenditure`

**yfinance fallback:**
```bash
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_fundamentals.py TICKER --sections cashflow --freq annual
```

### 1.2 Key Financial Ratios

```bash
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint key-ratios
```

**Extract:** `market_cap`, `enterprise_value`, `free_cash_flow_growth`, `revenue_growth`, `return_on_invested_capital`, `debt_to_equity`, `free_cash_flow_per_share`

### 1.3 Balance Sheet

```bash
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint balance-sheets --period annual --limit 1
```

**Extract:** `total_debt`, `cash_and_equivalents`, `current_investments`, `outstanding_shares`

**Fallback:** If `current_investments` missing, use 0

### 1.4 Analyst Estimates

```bash
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint analyst-estimates
```

**Extract:** `earnings_per_share` (forward estimates by fiscal year)

**Use:** Calculate implied EPS growth rate for cross-validation

### 1.5 Current Price

```bash
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint price
```

**Extract:** `price`

### 1.6 Company Facts

```bash
python ${CLAUDE_PLUGIN_ROOT}/tools/fetch_financial_datasets.py TICKER --endpoint company-facts
```

**Extract:** `sector`, `industry`, `market_cap`

**Use:** Determine appropriate WACC range from [sector-wacc.md](sector-wacc.md)

## Step 2: Calculate FCF Growth Rate

Calculate 5-year FCF CAGR from cash flow history.

**Cross-validate with:** `free_cash_flow_growth` (YoY), `revenue_growth`, analyst EPS growth

**Growth rate selection:**
- Stable FCF history → Use CAGR with 10-20% haircut
- Volatile FCF → Weight analyst estimates more heavily
- **Cap at 15%** (sustained higher growth is rare)

## Step 3: Estimate Discount Rate (WACC)

**Use the `sector` from company facts** to select the appropriate base WACC range from [sector-wacc.md](sector-wacc.md).

**Default assumptions:**
- Risk-free rate: 4%
- Equity risk premium: 5-6%
- Cost of debt: 5-6% pre-tax (~4% after-tax at 30% tax rate)

Calculate WACC using `debt_to_equity` for capital structure weights.

**Reasonableness check:** WACC should be 2-4% below `return_on_invested_capital` for value-creating companies.

**Sector adjustments:** Apply adjustment factors from [sector-wacc.md](sector-wacc.md) based on company-specific characteristics.

## Step 4: Run DCF Calculator

Pass all gathered inputs to the calculation engine:

```bash
python ${CLAUDE_PLUGIN_ROOT}/tools/calculate_dcf.py TICKER \
  --fcf-history "FCF_Y1,FCF_Y2,FCF_Y3,FCF_Y4,FCF_Y5" \
  --growth-rate RATE --wacc WACC --terminal-growth 0.025 \
  --total-debt DEBT --cash CASH --shares-outstanding SHARES \
  --current-price PRICE --current-ev EV \
  --decay-rate 0.05
```

The calculator handles:
- Projecting Years 1-5 FCF with annual growth decay
- Terminal value via Gordon Growth Model
- Discounting to present value
- Enterprise Value → Equity Value → Fair Value per share
- 3×3 sensitivity matrix (WACC ±1% × terminal growth 2.0/2.5/3.0%)
- Validation checks (EV comparison, terminal ratio, FCF/share cross-check)

## Step 5: Review Validation Checks

Examine the calculator's validation results:

1. **EV comparison**: Calculated EV should be within 30% of reported `enterprise_value`
   - If off by >30%, revisit WACC or growth assumptions and re-run

2. **Terminal value ratio**: Should be 50-80% of total EV for mature companies
   - If >90%, growth rate may be too high
   - If <40%, near-term projections may be aggressive

3. **Per-share cross-check**: Compare to `free_cash_flow_per_share × 15-25` as rough sanity check

If validation fails, adjust assumptions and re-run the calculator.

## Step 6: Present Report

Include the calculator's full output (valuation summary, key inputs, projected FCFs, sensitivity matrix, validations) plus:

1. **Your interpretation**: What the DCF implies about the stock's value
2. **Key assumptions**: Which inputs drive the most uncertainty (reference the sensitivity matrix)
3. **Comparison**: How the DCF fair value compares to current market price and analyst targets
4. **Caveats**: Standard DCF limitations plus company-specific risks

Consult [dcf-methodology.md](dcf-methodology.md) for guidance on when DCF is/isn't appropriate and common pitfalls.

## Output

Save the full report as: `reports/TICKER_dcf_valuation_YYYY-MM-DD.md`
