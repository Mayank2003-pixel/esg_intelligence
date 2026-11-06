import math
import os
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session
from .models import ESGRecord, Organization

NUMERIC_FIELDS = ["electricity_kwh", "renewable_kwh", "scope1_tco2e", "scope2_tco2e", "scope3_tco2e", "water_m3", "waste_tonnes", "recycled_tonnes", "employees", "female_employees", "male_employees", "employee_exits", "training_hours", "safety_incidents", "board_members", "independent_directors", "compliance_incidents", "ethics_violations", "audit_findings", "resolved_findings", "revenue_usd"]
METRICS = [
 {"key":"total_emissions","name":"Total carbon emissions","pillar":"Environmental","unit":"tCO₂e","formula":"Scope 1 + Scope 2 + Scope 3","direction":"lower","fields":["scope1_tco2e","scope2_tco2e","scope3_tco2e"]},
 {"key":"carbon_intensity","name":"Carbon intensity","pillar":"Environmental","unit":"tCO₂e/USD","formula":"Total emissions / revenue","direction":"lower","fields":["scope1_tco2e","scope2_tco2e","scope3_tco2e","revenue_usd"]},
 {"key":"renewable_pct","name":"Renewable energy","pillar":"Environmental","unit":"%","formula":"Renewable electricity / electricity × 100","direction":"higher","fields":["renewable_kwh","electricity_kwh"]},
 {"key":"water_m3","name":"Water consumption","pillar":"Environmental","unit":"m³","formula":"Reported consumption","direction":"lower","fields":["water_m3"]},
 {"key":"recycling_pct","name":"Waste recycling","pillar":"Environmental","unit":"%","formula":"Recycled waste / total waste × 100","direction":"higher","fields":["recycled_tonnes","waste_tonnes"]},
 {"key":"female_pct","name":"Women in workforce","pillar":"Social","unit":"%","formula":"Female employees / employees × 100","direction":"higher","fields":["female_employees","employees"]},
 {"key":"male_pct","name":"Men in workforce","pillar":"Social","unit":"%","formula":"Male employees / employees × 100","direction":"higher","fields":["male_employees","employees"]},
 {"key":"turnover_pct","name":"Employee turnover","pillar":"Social","unit":"%","formula":"Employee exits / reported period headcount × 100","direction":"lower","fields":["employee_exits","employees"]},
 {"key":"training_hours","name":"Employee training","pillar":"Social","unit":"hours","formula":"Reported total training hours","direction":"higher","fields":["training_hours"]},
 {"key":"safety_incidents","name":"Safety incidents","pillar":"Social","unit":"incidents","formula":"Reported incidents","direction":"lower","fields":["safety_incidents"]},
 {"key":"board_independence_pct","name":"Board independence","pillar":"Governance","unit":"%","formula":"Independent directors / board members × 100","direction":"higher","fields":["independent_directors","board_members"]},
 {"key":"audit_resolution_pct","name":"Audit resolution","pillar":"Governance","unit":"%","formula":"Resolved findings / audit findings × 100","direction":"higher","fields":["resolved_findings","audit_findings"]},
 {"key":"compliance_incidents","name":"Compliance incidents","pillar":"Governance","unit":"incidents","formula":"Reported incidents","direction":"lower","fields":["compliance_incidents"]},
]

def ratio(a, b):
    return None if a is None or b is None or b == 0 else round(a / b * 100, 2)

def scoring_weights():
    defaults={"environmental":.4,"social":.3,"governance":.3}
    try:
        weights={"environmental":float(os.getenv("ESG_WEIGHT_ENV",defaults["environmental"])),"social":float(os.getenv("ESG_WEIGHT_SOC",defaults["social"])),"governance":float(os.getenv("ESG_WEIGHT_GOV",defaults["governance"]))}
        total=sum(weights.values())
        return {k:v/total for k,v in weights.items()} if total>0 and all(v>=0 for v in weights.values()) else defaults
    except (TypeError,ValueError):return defaults

def record_values(r):
    vals = {f: getattr(r, f) for f in NUMERIC_FIELDS}
    emissions = None if any(vals[x] is None for x in ("scope1_tco2e", "scope2_tco2e", "scope3_tco2e")) else sum(vals[x] for x in ("scope1_tco2e", "scope2_tco2e", "scope3_tco2e"))
    female_pct=ratio(vals["female_employees"], vals["employees"])
    vals.update(total_emissions=emissions, carbon_intensity=None if emissions is None or vals["revenue_usd"] in (None,0) else emissions/vals["revenue_usd"], renewable_pct=ratio(vals["renewable_kwh"], vals["electricity_kwh"]), recycling_pct=ratio(vals["recycled_tonnes"], vals["waste_tonnes"]), female_pct=female_pct, male_pct=ratio(vals["male_employees"], vals["employees"]), turnover_pct=ratio(vals["employee_exits"], vals["employees"]), board_independence_pct=ratio(vals["independent_directors"], vals["board_members"]), audit_resolution_pct=ratio(vals["resolved_findings"], vals["audit_findings"]))
    return vals

def seeded(db: Session):
    if db.query(Organization).count(): return
    orgs = [("GreenTech Manufacturing", "Manufacturing"), ("Nexa Technologies", "IT Services"), ("UrbanBuild Infrastructure", "Infrastructure")]
    for oi, (name, industry) in enumerate(orgs):
        org = Organization(name=name, industry=industry); db.add(org); db.flush()
        rng = np.random.default_rng(210 + oi)
        for i, period in enumerate(pd.period_range("2023-01", periods=36, freq="M")):
            scale = [1.0, .68, 1.45][oi]
            base = scale * (1 - .003 * i)
            headcount=round([430,780,610][oi]*(1+.003*i)); women=round([142,302,180][oi]*(1+.003*i))
            row = dict(organization_id=org.id, period=str(period), electricity_kwh=round(62000*base*rng.normal(1,.055),1), renewable_kwh=round(21000*base*(1+.008*i)*rng.normal(1,.06),1), scope1_tco2e=round(32*base*rng.normal(1,.07),2), scope2_tco2e=round(24*base*rng.normal(1,.06),2), scope3_tco2e=round(68*base*rng.normal(1,.08),2), water_m3=round(1750*base*rng.normal(1,.07),1), waste_tonnes=round(39*base*rng.normal(1,.08),2), recycled_tonnes=round(22*base*rng.normal(1,.08),2), employees=headcount, female_employees=women, male_employees=headcount-women, employee_exits=int(rng.poisson(5)), training_hours=round(rng.normal(540,45),1), safety_incidents=int(rng.poisson([2,.5,4][oi])), board_members=9, independent_directors=6, compliance_incidents=int(rng.poisson(.35)), ethics_violations=int(rng.poisson(.2)), audit_findings=int(rng.poisson(3)+1), resolved_findings=int(rng.poisson(2)+1), revenue_usd=round([2100000,3300000,2700000][oi]*base*rng.normal(1,.04),2))
            if i in (8, 25) and oi == 0: row["scope1_tco2e"] *= 2.6
            if i == 15 and oi == 2: row["water_m3"] *= 2.8
            if i in (11, 29): row["scope3_tco2e"] = None
            db.add(ESGRecord(**row))
    db.commit()

def dashboard(db: Session, org_id: int, year: int | None = None):
    q = db.query(ESGRecord).filter_by(organization_id=org_id)
    if year: q = q.filter(ESGRecord.period.startswith(str(year)))
    rows = q.order_by(ESGRecord.period).all(); vals = [record_values(r) for r in rows]
    series = []
    for r, v in zip(rows, vals): series.append({"period":r.period, **{k:v[k] for k in ("total_emissions","carbon_intensity","scope1_tco2e","scope2_tco2e","scope3_tco2e","electricity_kwh","renewable_kwh","water_m3","waste_tonnes","recycling_pct","employees","female_pct","male_pct","female_employees","male_employees","turnover_pct","training_hours","safety_incidents","board_independence_pct","compliance_incidents","ethics_violations","audit_findings","audit_resolution_pct","revenue_usd")}})
    current = vals[-1] if vals else {}; previous = vals[-2] if len(vals)>1 else {}
    fields = ["total_emissions","renewable_pct","water_m3","recycling_pct","female_pct","turnover_pct","board_independence_pct"]
    kpis = [{"key":m,"value":current.get(m),"previous":previous.get(m),"change_pct":None if current.get(m) is None or not previous.get(m) else round((current[m]-previous[m])/abs(previous[m])*100,1),"unit":next((x["unit"] for x in METRICS if x["key"]==m),""),"name":next((x["name"] for x in METRICS if x["key"]==m),m)} for m in fields]
    pillars = {}
    guardrail_path=Path(__file__).resolve().parents[1]/"sample_data"/"score_guardrails.csv"
    guardrails=pd.read_csv(guardrail_path).set_index("metric")
    for pillar in ("Environmental","Social","Governance"):
        ms=[m for m in METRICS if m["pillar"]==pillar]
        # A transparent illustrative score, normalized to fixed policy guardrails, with a coverage threshold.
        normalized=[]
        for m in ms:
            val=current.get(m["key"])
            if val is None: continue
            bounds=guardrails.loc[m["key"]] if m["key"] in guardrails.index else {"lower":0,"upper":100}
            low,high=float(bounds["lower"]),float(bounds["upper"])
            if high<=low:continue
            score=min(100,max(0,(val-low)/(high-low)*100)); normalized.append(score if m["direction"]=="higher" else 100-score)
        pillars[pillar.lower()] = round(float(np.mean(normalized)),1) if len(normalized)>=max(2, math.ceil(len(ms)*.6)) else None
    weights=scoring_weights()
    scores={**pillars,"overall":round(sum(pillars[k]*weights[k] for k in weights),1) if all(v is not None for v in pillars.values()) else None,"weights":weights}
    return {"organization_id":org_id,"year":year,"count":len(rows),"kpis":kpis,"scores":scores,"series":series,"metrics":METRICS}

def insights(data):
    s=data["series"]; out=[]
    if len(s)<2:return out
    a,b=s[-2],s[-1]
    for key,label,threshold,good in [("total_emissions","Carbon emissions",5,False),("water_m3","Water use",8,False),("turnover_pct","Employee turnover",10,False),("renewable_pct","Renewable energy share",5,True),("recycling_pct","Waste recycling rate",5,True)]:
        old,new=a.get(key),b.get(key)
        if old is not None and new is not None and old and abs((new-old)/old*100)>=threshold:
            pct=round((new-old)/old*100,1); favorable=(pct>0)==good
            out.append({"title":f"{label} {'increased' if pct>0 else 'decreased'} {abs(pct)}%","detail":f"Changed from {old:.1f} to {new:.1f} between {a['period']} and {b['period']}; {'favorable' if favorable else 'needs attention'} movement.","pillar":"Environmental" if key in ("total_emissions","water_m3","renewable_pct","recycling_pct") else "Social","priority":"Low" if favorable else "Medium"})
    for x in s[-3:]:
        if x.get("audit_findings") is not None and x.get("audit_resolution_pct") is not None and x["audit_resolution_pct"]<60:
            out.append({"title":"Audit resolution is below 60%","detail":f"{x['period']}: {x['audit_resolution_pct']:.1f}% of findings resolved.","pillar":"Governance","priority":"High"}); break
    return out

def recommendations(data):
    out=[]
    for finding in insights(data):
        t=finding["title"]
        mapping=("Review energy and operational drivers; track tCO₂e monthly." if "Carbon" in t else "Investigate sites and implement water efficiency actions; track m³." if "Water" in t else "Review retention patterns and manager practices; track quarterly exits." if "turnover" in t else "Assess renewable procurement and on-site generation; track renewable share." if "Renewable" in t else "Review waste segregation and vendor recovery; track recycling share." if "recycling" in t else "Assign owners and due dates to open audit findings; monitor resolution rate.")
        out.append({"issue":t,"supporting_metric":finding["detail"],"action":mapping,"priority":finding["priority"],"improvement_measure":"Improve the supporting KPI over the next reporting period."})
    return out

def find_anomalies(rows):
    features=["electricity_kwh","scope1_tco2e","scope2_tco2e","water_m3","waste_tonnes","turnover_pct","safety_incidents"]
    data=[record_values(r) for r in rows]
    if len(data)<12:return []
    frame=pd.DataFrame(data)[features].replace([np.inf,-np.inf],np.nan)
    frame=frame.fillna(frame.median()).fillna(0)
    model=IsolationForest(contamination=.06,random_state=7,n_estimators=150); labels=model.fit_predict(frame); scores=model.decision_function(frame)
    result=[]
    for i,label in enumerate(labels):
        if label!=-1:continue
        deviations={c:abs(frame.iloc[i][c]-frame[c].median())/(frame[c].mad() if hasattr(frame[c],"mad") else frame[c].std()+1e-9) for c in features}
        metric=max(deviations,key=deviations.get); value=float(frame.iloc[i][metric]); result.append({"period":rows[i].period,"metric":metric,"value":value,"severity":"High" if scores[i]<-.08 else "Medium","explanation":f"{metric.replace('_',' ')} was unusually far from its historical pattern for this organization. This is a review signal, not a finding of misconduct."})
    return result
