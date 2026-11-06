"""Generate a deterministic, synthetic CSV for the three demonstration organizations."""
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db import Base
from app.analytics import NUMERIC_FIELDS, seeded
from app.models import Organization, ESGRecord

target=Path(__file__).parent/"sample_data"/"esg_demo_monthly.csv"
target.parent.mkdir(exist_ok=True)
engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
Base.metadata.create_all(engine)
with Session(engine) as db:
    seeded(db)
    rows=[]
    for org in db.query(Organization).order_by(Organization.id):
        for record in db.query(ESGRecord).filter_by(organization_id=org.id).order_by(ESGRecord.period):
            rows.append({"organization":org.name,"industry":org.industry,"period":record.period,**{field:getattr(record,field) for field in NUMERIC_FIELDS}})
    frame=pd.DataFrame(rows)
    frame.to_csv(target,index=False)
    frame.to_excel(target.with_suffix(".xlsx"),index=False)
    upload_sample=frame[frame.organization.eq("GreenTech Manufacturing")].tail(12).copy()
    upload_sample["period"]=[f"2026-{month:02d}" for month in range(1,13)]
    upload_sample=upload_sample[["period",*NUMERIC_FIELDS]]
    upload_sample.to_excel(target.parent/"upload_sample.xlsx",index=False)
    upload_sample.to_csv(target.parent/"upload_sample.csv",index=False)
print(target)
