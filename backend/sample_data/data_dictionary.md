# ESG demonstration data dictionary

All values in `esg_demo_monthly.csv` are deterministic, fictional demonstration values for GreenTech Manufacturing, Nexa Technologies, and UrbanBuild Infrastructure. The data cover 36 months from January 2023 through December 2025. Intentional outliers and missing Scope 3 observations illustrate quality and anomaly review. They are not company disclosures.

| Column | Meaning | Unit / convention |
|---|---|---|
| organization | Fictional organization name | Text |
| industry | Demonstration industry grouping | Text |
| period | Monthly reporting period | YYYY-MM |
| electricity_kwh | Electricity consumed | kWh |
| renewable_kwh | Renewable electricity consumed | kWh; no greater than total electricity |
| scope1_tco2e | Direct emissions | tCO₂e |
| scope2_tco2e | Purchased energy emissions | tCO₂e |
| scope3_tco2e | Other indirect emissions | tCO₂e; missing where unavailable |
| water_m3 | Water consumed | m³ |
| waste_tonnes | Total waste generated | metric tonnes |
| recycled_tonnes | Waste recycled | metric tonnes |
| employees | Workforce headcount | People |
| female_employees | Female workforce headcount | People; aggregate only |
| male_employees | Male workforce headcount | People; aggregate only, reported separately |
| employee_exits | Employees leaving in period | People |
| training_hours | Employee training delivered | Hours |
| safety_incidents | Workplace safety incidents | Count |
| board_members | Total board members | People |
| independent_directors | Independent board members | People |
| compliance_incidents | Compliance incidents reported | Count |
| ethics_violations | Ethics violations reported | Count |
| audit_findings | Audit findings identified | Count |
| resolved_findings | Audit findings resolved | Count |
| revenue_usd | Fictional revenue used for intensity illustration | USD |

Scope emissions are already in tCO₂e. No emission factors are applied to energy or fuel consumption. Ratio metrics are calculated only when both inputs exist and the denominator is nonzero. Missing Scope 3 emissions make total emissions unavailable for that period; missing values are not imputed in reported KPI calculations.

## Calculated KPI formulas

- Total emissions = Scope 1 + Scope 2 + Scope 3; unavailable if any scope is missing.
- Carbon intensity = total emissions / revenue (USD).
- Renewable energy share = renewable kWh / electricity kWh × 100.
- Recycling rate = recycled tonnes / total waste tonnes × 100.
- Workforce representation = gender-specific reported headcount / total employees × 100. No gender is inferred from the remainder.
- Employee turnover = period exits / reported period headcount × 100. Average headcount is not available in this sample.
- Board independence = independent directors / board members × 100.
- Audit resolution = resolved findings / audit findings × 100.

Zero denominators and missing inputs produce unavailable ratio values. The configurable ESG score uses documented direction-aware guardrails and requires at least 60% metric coverage per pillar. Default pillar weights (40% environmental, 30% social, 30% governance) are illustrative, not an industry standard.
