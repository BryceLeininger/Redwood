# 2026 Pro Forma Workbook Reference

This agent is aligned to the workbook structure in `11 - Pro Forma_2026_New.xlsx`.

## Sheet Roles

- `Land`: deal-level land inputs including lots, lot takedowns, purchase price per lot, deposit, and closing schedule.
- `Product`: product mix, square footage, pricing, incentives, and direct vertical cost assumptions.
- `Operations`: absorption, starts, sales opening, indirect field overhead, architecture, and capitalized marketing assumptions.
- `Summary`: investment summary, schedule summary, income statement, IRR, and peak investment outputs.

## Key Summary Metrics Used By The Agent

- `Total Land Cost`
- `Land Cost per Lot`
- `Land Development & Entitlement`
- `Project Management`
- `Total Site Improvements`
- `Other Land Costs`
- `Total Finished Lot Cost`
- `Finished Cost per Lot`
- `Average Net Sales Price`
- `Lot Cost % of ASP`
- `Revenue`
- `House Costs`
- `Total Cost of Sales`
- `Gross Margin`
- `Sales Commissions & Other Sales Costs`
- `Contribution Margin`
- `Capitalized Marketing`
- `Corporate Charge`
- `Pre-G&A Contribution`
- `IRR - Pre-G&A Contribution`
- `Peak Investment`

## Default Assumption Benchmarks From The Sample Workbook

- Average net sales price: about `$728,500` per home
- Land cost: about `$67,967` per lot
- Finished lot cost: about `$211,052` per lot
- Gross margin: about `21.95%`
- Pre-G&A contribution: about `15.06%`
- Pre-G&A IRR: about `22.64%`
- Peak investment: about `$17.16M`
- Monthly absorption: about `3.1` homes per month
- Build cycle: about `5` months

## JSON Input Mapping

- `gross_acres`, `product_series[].lots`: mirrors `Summary` property summary and `Land` lot counts.
- `land_purchase_price_per_lot`, `land_purchase_events`, `earnest_money_deposit`: mirrors `Land` purchase structure.
- `land_development_cost_total`, `project_management_cost_total`, `other_land_costs_total`: mirrors `Summary` land and site improvement sections.
- `product_series[].base_house_price`, `options_pct`, `price_incentives_pct`, `mortgage_incentives_pct`: mirrors `Product` pricing assumptions.
- `product_series[].direct_cost_psf`, `direct_cost_contingency_pct`, `permit_fees_per_unit`, `tap_fees_per_unit`: mirrors `Product` direct cost inputs.
- `indirect_field_overhead_total` or `indirect_field_overhead_per_month`: mirrors `Operations` indirect and field overhead.
- `architecture_engineering_total`: mirrors `Operations` architecture and engineering.
- `capitalized_marketing_total`: mirrors `Summary` capitalized marketing.
- `sales_commission_pct`, `corporate_charge_pct`: mirrors `Summary` below-the-line deductions.
- `monthly_absorption`, `build_cycle_months`, `months_to_first_home_start`, `months_to_sales_open`: mirrors `Operations` schedule assumptions.

## Modeling Notes

- The agent keeps the actual land basis fixed across downside scenarios, matching how an acquisition decision is tested after price is negotiated.
- Downside cases stress sales prices, non-land costs, and absorption pace.
- Residual land value is calculated against the target pre-G&A contribution margin, which is the most practical offer-price anchor for early screening.
- Cash flow IRR is approximated from monthly deal cash flows, not copied from the workbook formulas cell-by-cell.
