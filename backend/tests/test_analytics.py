import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db import Base
from app.models import Organization, ESGRecord
from app.analytics import record_values, dashboard, seeded, scoring_weights

def make_db():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)

def test_ratios_and_totals_use_expected_formulas():
    row=ESGRecord(organization_id=1,period="2025-01",scope1_tco2e=10,scope2_tco2e=20,scope3_tco2e=30,revenue_usd=1200,electricity_kwh=100,renewable_kwh=25,waste_tonnes=8,recycled_tonnes=6,employees=100,female_employees=42,male_employees=55,employee_exits=5,board_members=10,independent_directors=7,audit_findings=4,resolved_findings=3)
    values=record_values(row)
    assert values["total_emissions"]==60
    assert values["carbon_intensity"]==0.05
    assert values["renewable_pct"]==25
    assert values["recycling_pct"]==75
    assert values["turnover_pct"]==5
    assert values["female_pct"]==42 and values["male_pct"]==55
    assert values["board_independence_pct"]==70
    assert values["audit_resolution_pct"]==75

def test_missing_values_and_zero_denominators_stay_unavailable():
    row=ESGRecord(organization_id=1,period="2025-01",scope1_tco2e=10,scope2_tco2e=20,scope3_tco2e=None,electricity_kwh=0,renewable_kwh=10,waste_tonnes=0,recycled_tonnes=2,employees=0,female_employees=3)
    values=record_values(row)
    assert values["total_emissions"] is None
    assert values["renewable_pct"] is None
    assert values["recycling_pct"] is None
    assert values["female_pct"] is None
    assert values["male_pct"] is None

def test_seed_builds_36_periods_for_three_demo_organizations():
    db=make_db()
    seeded(db)
    assert db.query(Organization).count()==3
    assert db.query(ESGRecord).count()==108
    assert db.query(ESGRecord).filter_by(organization_id=1).count()==36
    db.close()

def test_dashboard_score_is_unavailable_without_adequate_pillar_coverage():
    db=make_db();o=Organization(name="Test",industry="Other");db.add(o);db.flush()
    db.add(ESGRecord(organization_id=o.id,period="2025-01",scope1_tco2e=1,scope2_tco2e=2,scope3_tco2e=3));db.commit()
    d=dashboard(db,o.id)
    assert d["scores"]["overall"] is None
    assert d["kpis"][0]["value"]==6
    db.close()

def test_scoring_weights_are_configurable_and_normalized(monkeypatch):
    monkeypatch.setenv("ESG_WEIGHT_ENV","5")
    monkeypatch.setenv("ESG_WEIGHT_SOC","3")
    monkeypatch.setenv("ESG_WEIGHT_GOV","2")
    assert scoring_weights()=={"environmental":.5,"social":.3,"governance":.2}
