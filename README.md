# ESG Intelligence

A portfolio-grade ESG analytics platform with a FastAPI/SQLite analytical backend and a React dashboard. Demonstration records and benchmarks are synthetic and must not be treated as company disclosures.

## Start locally

Requirements: Python 3.11+ and Node.js 20+.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, create an account, then use **Organizations → Add an organization** before importing your own data. API docs are at http://localhost:8000/docs. SQLite is created at `backend/esg_intelligence.db`; shared demo organizations and 36 monthly periods seed on first run. Copy the root `.env.example` to `backend/.env` to configure storage, CORS, and score weights. Copy `frontend/.env.example` to `frontend/.env` if the API uses a different address.

## Features

- Registration, sign-in, editable user profiles/passwords, and private user-owned organizations alongside clearly labeled shared demo organizations.
- Organization and reporting year filters, executive overview, pillar dashboards, trends, benchmark comparisons, and metric dictionary.
- CSV/XLSX upload with automatic schema detection. Canonical monthly ESG files receive row validation and ESG-specific calculations; files with different or extra columns are preserved as flexible datasets with inferred field types, numeric summaries, and a dynamic row explorer. Uploads support up to 20 MB, 20,000 rows, and 100 columns. Invalid rows in canonical ESG imports are reported rather than silently imported.
- Reusable ESG metric registry, deterministic KPI formulas, explicit missing values, configurable scoring, rule-based observations and recommendations.
- Isolation Forest anomaly screening when sufficient records exist, with explanation and acknowledgement.
- PDF report and Excel data export endpoints.

## Architecture

`backend/app` contains SQLAlchemy models, authentication, synthetic-data generation, validation/ingestion, calculations, analytics, and API routes. `frontend/src` contains the Vite React application. SQLite is used for local development; SQLAlchemy is used for persistence. Passwords are stored using salted PBKDF2 hashes. Signed bearer tokens expire after 12 hours. A random signing key is generated locally and persisted in ignored `backend/.jwt_secret` unless `JWT_SECRET` is set; set a stable secret in `backend/.env` if several server instances will share the database. Owned organizations and their records are isolated by account; the three explicitly labeled demonstration organizations are shared and read-only. ESG scores use configurable illustrative pillar weights (40/30/30 by default), direction-aware normalization against editable guardrails, and report coverage; scores with insufficient coverage are unavailable. Set `ESG_WEIGHT_ENV`, `ESG_WEIGHT_SOC`, and `ESG_WEIGHT_GOV` in `backend/.env`; the values are normalized to sum to 1. Edit `backend/sample_data/score_guardrails.csv` or `industry_benchmarks.csv` to update the scoring ranges and illustrative sector references; changes are read from those datasets when analytics are requested. See the [sample data dictionary](backend/sample_data/data_dictionary.md). The multi-organization history is in `backend/sample_data/esg_demo_monthly.csv`; the downloadable upload workbook has 12 future periods suitable for trying the import flow against an organization you own.

## Flexible dataset imports

Files do not need to match the ESG template. Noncanonical schemas are stored with their original columns and displayed through a dataset-driven overview with inferred numeric summaries and a row table. Flexible imports do not invent ESG units, pillar scores, or period-over-period calculations. Use the canonical template when you want the registered ESG formulas, scores, and benchmarks.

## Supported upload columns

`organization` (optional), `period` (YYYY-MM), `electricity_kwh`, `renewable_kwh`, `scope1_tco2e`, `scope2_tco2e`, `scope3_tco2e`, `water_m3`, `waste_tonnes`, `recycled_tonnes`, `employees`, `female_employees`, `male_employees`, `employee_exits`, `training_hours`, `safety_incidents`, `board_members`, `independent_directors`, `compliance_incidents`, `ethics_violations`, `audit_findings`, `resolved_findings`, and `revenue_usd`.

## Limitations and assumptions

Sample data describes fictional organizations. Shared demo organizations are read-only; imported measurements, reports, and anomaly reviews belong in an organization created by your account. Emission factors are not applied by default: the system expects emissions already in tCO₂e. Missing values remain missing; ratios with missing inputs or zero denominators are unavailable. Uploads accept CSV and Excel. Accounts use local email/password sign-in; email verification, password reset, SSO, and role administration are not included. Forecasts are omitted because the available data is not enough to support defensible forecasting.

## Development

Install backend requirements and frontend npm dependencies as shown above. Run backend checks with `python -m pytest -q` from `backend`; the frontend production build can be checked with `npm run build` from `frontend`. Interactive API docs are at `/docs`; the API is versioned under `/api/v1`.

## Main folders

- `backend/app`: database models, seed generator, ESG formulas, validation/ingestion, analytics, API and report generation.
- `backend/tests`: unit checks for formulas, missing data, scoring coverage and synthetic seeding.
- `backend/sample_data`: synthetic CSV/XLSX histories, a clean upload workbook, editable benchmark/score-range data, and the data dictionary.
- `frontend/src`: responsive React dashboard, charts, page modules, styles and API client.
