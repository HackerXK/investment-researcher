# Live Chat Evaluation Questions

This reference catalog mirrors the reusable question corpus in
`tests/fixtures/chat_eval_questions.py`.

Use it alongside the live host-side evaluation runner:

```bash
python scripts/run_live_chat_eval.py --smoke
```

The README links here for the detailed question list, smoke-subset contents, and
eval-specific notes.

## Smoke Subset

Use this smaller subset first to validate environment wiring, SSE capture, and
the evaluator loop:

1. aapl-ttm-revenue-net-income
2. nvda-latest-annual-ratios
3. xom-annual-cash-flow-summary
4. aapl-nvda-xom-fcf-ranking

Run it with:

```bash
python scripts/run_live_chat_eval.py --smoke
```

## Full Corpus

| Question ID | Difficulty | Primary tools | Prompt |
| --- | --- | --- | --- |
| aapl-ttm-revenue-net-income | simple | get_ttm_metrics | What are Apple's latest trailing-twelve-month revenue and net income? Answer with the figures and a short interpretation. |
| nvda-latest-annual-ratios | simple | get_latest_ratios | What are NVIDIA's latest annual gross profit margin, operating margin, and return on equity? |
| xom-annual-cash-flow-summary | simple | get_cashflow_pivot | For Exxon Mobil's most recent annual period only, report operating cash flow, capex, and free cash flow. Do not include prior years or any extra metrics. |
| meta-recent-8k-events | simple | get_material_events | What recent 8-K material events has Meta reported since 2024-01-01? List the item codes and explain them briefly. |
| aapl-proxy-ceo-compensation | simple | get_proxy_statement_data | From Apple's recent proxy statement, what does it report about CEO compensation and pay-versus-performance? |
| brk-top-13f-holdings | simple | summarize_institutional_holdings | What are Berkshire Hathaway's top holdings in its latest 13F filing, and how concentrated is the portfolio? |
| aapl-growth-and-margin-trend | complex | get_growth_rates, get_ratio_timeseries | How have Apple's revenue growth and net profit margin changed over the last four annual periods? Give the direction and the numbers. |
| amzn-quarterly-trend-and-ttm-fcf | complex | get_quarterly_detail, get_ttm_metrics, get_ttm_ratios | Using the last eight quarters, describe Amazon's revenue trend and latest trailing-twelve-month free cash flow, and tell me whether the margin picture is improving. |
| meta-insider-sells-and-proxy | complex | summarize_insider_sells, get_proxy_statement_data | Since 2024-01-01, have there been notable insider sells at Meta, and what does the latest proxy statement say about CEO compensation? |
| nvda-latest-10k-risk-themes | complex | list_filings, read_filing | From NVIDIA's latest 10-K, what are two risk themes management highlights? Cite the accession number. |
| xom-8k-events-and-cashflow | complex | get_material_events, get_cashflow_pivot | Have there been any recent 8-K material events for Exxon Mobil in the last year, and how does its latest annual free cash flow compare with capex? |
| aapl-nvda-xom-fcf-ranking | complex | compare_metric_across_companies | Using only the latest annual free cash flow values, rank AAPL, NVDA, and XOM from highest to lowest. Provide only the ranking and the free cash flow figure for each company, with no extra metrics or commentary. |

## Notes

- The corpus intentionally mixes one-tool lookups with multi-tool synthesis.
- Filing-heavy questions such as nvda-latest-10k-risk-themes, brk-top-13f-holdings, and the proxy-heavy cases are not in the smoke subset because they depend more heavily on local EDGAR cache coverage.
- The evaluator marks both pass and fail cases with explicit reasons and logs unsupported claims or missing facts when present.
- The live harness enforces a 30-second budget for evidence collection, chat generation, and evaluator grading per question.