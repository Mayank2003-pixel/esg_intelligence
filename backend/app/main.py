import io, json, os, re, math
import base64, hashlib, hmac, secrets
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pandas as pd
from fastapi import FastAPI, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text, or_
from sqlalchemy.exc import IntegrityError
from .db import Base, SessionLocal, engine
from .models import Organization, ESGRecord, UploadJob, AnomalyEvent, UserAccount, FlexibleDataset
from .analytics import NUMERIC_FIELDS, METRICS, seeded, dashboard, insights, recommendations, find_anomalies

app=FastAPI(title="ESG Intelligence API",version="1.0.0",description="Analytics for synthetic and user-uploaded ESG measurements.")
app.add_middleware(CORSMiddleware,allow_origins=[os.getenv("FRONTEND_ORIGIN","http://localhost:5173")],allow_methods=["*"],allow_headers=["*"])

def openapi_with_bearer():
    if app.openapi_schema:return app.openapi_schema
    schema=get_openapi(title=app.title,version=app.version,description=app.description,routes=app.routes)
    schema.setdefault("components",{}).setdefault("securitySchemes",{})["BearerAuth"]={"type":"http","scheme":"bearer"}
    public={"/api/v1/health","/api/v1/auth/register","/api/v1/auth/login"}
    for path,methods in schema.get("paths",{}).items():
        if path in public:continue
        for operation in methods.values():operation["security"]=[{"BearerAuth":[]}]
    app.openapi_schema=schema
    return schema

app.openapi=openapi_with_bearer

def load_jwt_secret():
    configured=os.getenv("JWT_SECRET")
    if configured:return configured
    path=Path(__file__).resolve().parents[1]/".jwt_secret"
    if path.exists():return path.read_text(encoding="utf-8").strip()
    secret=secrets.token_urlsafe(48);path.write_text(secret,encoding="utf-8");return secret

JWT_SECRET=load_jwt_secret()
TOKEN_TTL_HOURS=int(os.getenv("TOKEN_TTL_HOURS","12"))
PUBLIC_PATHS={"/api/v1/health","/api/v1/auth/register","/api/v1/auth/login","/docs","/redoc","/openapi.json"}

def b64url(raw:bytes)->str:return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
def create_token(user_id:int)->str:
    header=b64url(json.dumps({"alg":"HS256","typ":"JWT"},separators=(",",":")).encode())
    payload=b64url(json.dumps({"sub":str(user_id),"exp":int((datetime.now(timezone.utc)+timedelta(hours=TOKEN_TTL_HOURS)).timestamp())},separators=(",",":")).encode())
    body=f"{header}.{payload}"
    signature=b64url(hmac.new(JWT_SECRET.encode(),body.encode(),hashlib.sha256).digest())
    return f"{body}.{signature}"

def decode_token(token:str)->int|None:
    try:
        header,payload,signature=token.split(".");body=f"{header}.{payload}"
        expected=b64url(hmac.new(JWT_SECRET.encode(),body.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(signature,expected):return None
        claims=json.loads(base64.urlsafe_b64decode(payload+"="*(-len(payload)%4)))
        if int(claims.get("exp",0))<int(datetime.now(timezone.utc).timestamp()):return None
        return int(claims["sub"])
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):return None

def hash_password(password:str)->str:
    salt=secrets.token_bytes(16);digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,310_000)
    return f"pbkdf2_sha256${b64url(salt)}${b64url(digest)}"

def verify_password(password:str,stored:str)->bool:
    try:
        scheme,salt,digest=stored.split("$")
        if scheme!="pbkdf2_sha256":return False
        actual=hashlib.pbkdf2_hmac("sha256",password.encode(),base64.urlsafe_b64decode(salt+"="*(-len(salt)%4)),310_000)
        return hmac.compare_digest(b64url(actual),digest)
    except (ValueError,TypeError):return False

def user_dict(user:UserAccount):return {"id":user.id,"email":user.email,"full_name":user.full_name,"created_at":user.created_at.isoformat()}

def org_access(db:Session,organization_id:int,user_id:int)->Organization:
    organization=db.get(Organization,organization_id)
    if organization is None or (organization.owner_id is not None and organization.owner_id!=user_id):raise HTTPException(404,"Organization not found")
    return organization

def org_write_access(db:Session,organization_id:int,user_id:int)->Organization:
    organization=org_access(db,organization_id,user_id)
    if organization.owner_id!=user_id:raise HTTPException(403,"Create a private organization before changing shared demonstration data")
    return organization

@app.middleware("http")
async def require_login(request:Request,call_next):
    if request.method=="OPTIONS" or request.url.path in PUBLIC_PATHS:return await call_next(request)
    auth=request.headers.get("authorization","")
    user_id=decode_token(auth[7:]) if auth.lower().startswith("bearer ") else None
    if user_id is None:return JSONResponse({"detail":"Sign in to continue"},status_code=401)
    with SessionLocal() as db:
        user=db.get(UserAccount,user_id)
        if user is None:return JSONResponse({"detail":"Session is no longer valid"},status_code=401)
        org_id=request.query_params.get("organization_id")
        if org_id:
            try:org_access(db,int(org_id),user_id)
            except (ValueError,HTTPException) as exc:
                if isinstance(exc,HTTPException):return JSONResponse({"detail":exc.detail},status_code=exc.status_code)
                return JSONResponse({"detail":"Invalid organization"},status_code=400)
        match=re.match(r"^/api/v1/ingestion/jobs/(\d+)",request.url.path)
        if match:
            job=db.get(UploadJob,int(match.group(1)))
            if job is not None:
                try:org_access(db,job.organization_id,user_id)
                except HTTPException:return JSONResponse({"detail":"Import job not found"},status_code=404)
        match=re.match(r"^/api/v1/ml/anomalies/(\d+)/acknowledge$",request.url.path)
        if match:
            event=db.get(AnomalyEvent,int(match.group(1)))
            if event is not None:
                try:org_access(db,event.organization_id,user_id)
                except HTTPException:return JSONResponse({"detail":"Anomaly not found"},status_code=404)
        request.state.user_id=user_id
    return await call_next(request)

def db_session():
    db=SessionLocal()
    try: yield db
    finally: db.close()

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    tables=set(inspect(engine).get_table_names())
    if "uploaded_files" in tables and "cleaned_path" not in {c["name"] for c in inspect(engine).get_columns("uploaded_files")}:
        with engine.begin() as conn:conn.execute(text("ALTER TABLE uploaded_files ADD COLUMN cleaned_path VARCHAR(500)"))
    if "esg_records" in tables and "male_employees" not in {c["name"] for c in inspect(engine).get_columns("esg_records")}:
        with engine.begin() as conn:conn.execute(text("ALTER TABLE esg_records ADD COLUMN male_employees FLOAT"))
    if "organizations" in tables and "owner_id" not in {c["name"] for c in inspect(engine).get_columns("organizations")}:
        with engine.begin() as conn:conn.execute(text("ALTER TABLE organizations ADD COLUMN owner_id INTEGER REFERENCES user_accounts(id)"))
    with SessionLocal() as db: seeded(db)

@app.get("/api/v1/health")
def health():return {"status":"ok"}

class RegisterBody(BaseModel):
    email:str=Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",max_length=255)
    full_name:str=Field(min_length=2,max_length=160)
    password:str=Field(min_length=8,max_length=128)

class LoginBody(BaseModel):
    email:str=Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",max_length=255)
    password:str

class ProfileBody(BaseModel):
    email:str|None=Field(default=None,pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",max_length=255)
    full_name:str|None=Field(default=None,min_length=2,max_length=160)
    current_password:str|None=None
    new_password:str|None=Field(default=None,min_length=8,max_length=128)

class OrganizationBody(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    industry:str=Field(min_length=2,max_length=80)

@app.post("/api/v1/auth/register")
def register(body:RegisterBody,db:Session=Depends(db_session)):
    user=UserAccount(email=body.email.lower().strip(),full_name=body.full_name.strip(),password_hash=hash_password(body.password))
    db.add(user)
    try:db.commit();db.refresh(user)
    except IntegrityError:db.rollback();raise HTTPException(409,"An account with this email already exists")
    return {"access_token":create_token(user.id),"token_type":"bearer","user":user_dict(user)}

@app.post("/api/v1/auth/login")
def login(body:LoginBody,db:Session=Depends(db_session)):
    user=db.query(UserAccount).filter_by(email=body.email.lower().strip()).first()
    if user is None or not verify_password(body.password,user.password_hash):raise HTTPException(401,"Email or password is incorrect")
    return {"access_token":create_token(user.id),"token_type":"bearer","user":user_dict(user)}

@app.get("/api/v1/auth/me")
def get_profile(request:Request,db:Session=Depends(db_session)):
    user=db.get(UserAccount,request.state.user_id)
    return user_dict(user)

@app.patch("/api/v1/auth/me")
def update_profile(body:ProfileBody,request:Request,db:Session=Depends(db_session)):
    user=db.get(UserAccount,request.state.user_id)
    if body.email:user.email=body.email.lower().strip()
    if body.full_name:user.full_name=body.full_name.strip()
    if body.new_password:
        if not body.current_password or not verify_password(body.current_password,user.password_hash):raise HTTPException(400,"Current password is required and must be correct")
        user.password_hash=hash_password(body.new_password)
    try:db.commit();db.refresh(user)
    except IntegrityError:db.rollback();raise HTTPException(409,"An account with this email already exists")
    return user_dict(user)

@app.get("/api/v1/organizations")
def organizations(request:Request,db:Session=Depends(db_session)):
    uid=request.state.user_id
    query=db.query(Organization).filter(or_(Organization.owner_id.is_(None),Organization.owner_id==uid))
    return [{"id":o.id,"name":o.name,"industry":o.industry,"demonstration":o.demonstration,"owned":o.owner_id==uid} for o in query.order_by(Organization.id)]

@app.post("/api/v1/organizations",status_code=201)
def create_organization(body:OrganizationBody,request:Request,db:Session=Depends(db_session)):
    org=Organization(name=body.name.strip(),industry=body.industry.strip(),demonstration=False,owner_id=request.state.user_id)
    db.add(org)
    try:db.commit();db.refresh(org)
    except IntegrityError:db.rollback();raise HTTPException(409,"An organization with this name already exists")
    return {"id":org.id,"name":org.name,"industry":org.industry,"demonstration":False,"owned":True}

@app.patch("/api/v1/organizations/{organization_id}")
def update_organization(organization_id:int,body:OrganizationBody,request:Request,db:Session=Depends(db_session)):
    org=db.get(Organization,organization_id)
    if org is None or org.owner_id!=request.state.user_id:raise HTTPException(404,"Organization not found")
    org.name=body.name.strip();org.industry=body.industry.strip()
    try:db.commit();db.refresh(org)
    except IntegrityError:db.rollback();raise HTTPException(409,"An organization with this name already exists")
    return {"id":org.id,"name":org.name,"industry":org.industry,"demonstration":False,"owned":True}

@app.delete("/api/v1/organizations/{organization_id}",status_code=204)
def delete_organization(organization_id:int,request:Request,db:Session=Depends(db_session)):
    org=db.get(Organization,organization_id)
    if org is None or org.owner_id!=request.state.user_id:raise HTTPException(404,"Organization not found")
    if any(db.query(model).filter_by(organization_id=organization_id).first() for model in (ESGRecord,UploadJob,AnomalyEvent,FlexibleDataset)):raise HTTPException(409,"This organization has related data and cannot be deleted")
    db.delete(org);db.commit()

@app.get("/api/v1/metrics")
def metrics():return METRICS

@app.get("/api/v1/analytics/overview")
def overview(organization_id:int,year:int|None=None,db:Session=Depends(db_session)):
    if not db.get(Organization,organization_id):raise HTTPException(404,"Organization not found")
    return dashboard(db,organization_id,year)

@app.get("/api/v1/analytics/pillar/{pillar}")
def pillar(pillar:str,organization_id:int,year:int|None=None,db:Session=Depends(db_session)):
    if pillar not in ("environmental","social","governance"):raise HTTPException(404,"Unknown analytics pillar")
    data=dashboard(db,organization_id,year); keys={"environmental":["total_emissions","carbon_intensity","scope1_tco2e","scope2_tco2e","scope3_tco2e","electricity_kwh","renewable_kwh","renewable_pct","water_m3","waste_tonnes","recycling_pct"],"social":["employees","female_pct","male_pct","female_employees","male_employees","turnover_pct","training_hours","safety_incidents"],"governance":["board_independence_pct","compliance_incidents","ethics_violations","audit_findings","audit_resolution_pct"]}[pillar]
    return {"pillar":pillar,"count":data["count"],"series":[{"period":r["period"],**{k:r.get(k) for k in keys}} for r in data["series"]],"kpis":[k for k in data["kpis"] if k["key"] in keys],"score":data["scores"].get(pillar),"insights":insights(data)}

@app.get("/api/v1/analytics/benchmarking")
def benchmarking(organization_id:int,year:int|None=None,db:Session=Depends(db_session)):
    o=db.get(Organization,organization_id)
    if not o:raise HTTPException(404,"Organization not found")
    d=dashboard(db,organization_id,year); last=d["series"][-1] if d["series"] else {}
    # Reference values live in a replaceable dataset; changing it affects subsequent requests without code edits.
    benchmark_file=Path(__file__).resolve().parents[1]/"sample_data"/"industry_benchmarks.csv"
    benchmark_rows=pd.read_csv(benchmark_file)
    peer=benchmark_rows[benchmark_rows["industry"].str.casefold()==o.industry.casefold()]
    if peer.empty:return {"industry":o.industry,"label":"No illustrative benchmark is available for this industry. Add compatible peer data to enable a comparison.","items":[]}
    benchmark=peer.iloc[0];source=str(benchmark["source"])
    ref={k:float(benchmark[k]) for k in ("carbon_intensity","renewable_pct","water_m3","recycling_pct","female_pct","turnover_pct","board_independence_pct")}
    vals={"carbon_intensity":last.get("carbon_intensity"),"renewable_pct":(last.get("renewable_kwh")/last.get("electricity_kwh")*100 if last.get("renewable_kwh") is not None and last.get("electricity_kwh") else None),"water_m3":last.get("water_m3"),"recycling_pct":last.get("recycling_pct"),"female_pct":last.get("female_pct"),"turnover_pct":last.get("turnover_pct"),"board_independence_pct":last.get("board_independence_pct")}
    lower={"carbon_intensity","water_m3","turnover_pct"}
    return {"industry":o.industry,"label":source,"items":[{"metric":k,"organization":v,"benchmark":ref[k],"gap":None if v is None else round(v-ref[k],8 if k=="carbon_intensity" else 1),"unit":"tCO₂e/USD" if k=="carbon_intensity" else "%" if k.endswith("pct") else "m³","performance":None if v is None else ("Better" if (v<ref[k] if k in lower else v>ref[k]) else "Needs attention")} for k,v in vals.items()]}

@app.get("/api/v1/insights")
def get_insights(organization_id:int,year:int|None=None,db:Session=Depends(db_session)):return insights(dashboard(db,organization_id,year))

@app.get("/api/v1/recommendations")
def get_recommendations(organization_id:int,year:int|None=None,db:Session=Depends(db_session)):return recommendations(dashboard(db,organization_id,year))

@app.post("/api/v1/ingestion/upload")
async def upload(request:Request,file:UploadFile=File(...),organization_id:int=Form(...),db:Session=Depends(db_session)):
    org_write_access(db,organization_id,request.state.user_id)
    ext=Path(file.filename or "").suffix.lower()
    if ext not in (".csv",".xlsx",".xls"):raise HTTPException(400,"Upload a CSV or Excel file")
    content=await file.read()
    try: frame=pd.read_csv(io.BytesIO(content)) if ext==".csv" else pd.read_excel(io.BytesIO(content))
    except Exception as e:raise HTTPException(400,f"Could not read the uploaded file: {e}")
    if len(content)>20*1024*1024:raise HTTPException(413,"Files are limited to 20 MB")
    raw_columns=[str(c).strip().lower() or f"column_{i+1}" for i,c in enumerate(frame.columns)]
    seen_columns={}; columns=[]
    for col in raw_columns:
        seen_columns[col]=seen_columns.get(col,0)+1
        columns.append(col if seen_columns[col]==1 else f"{col}_{seen_columns[col]}")
    frame.columns=columns
    canonical_columns=set(NUMERIC_FIELDS)|{"period","organization"}
    if "period" not in frame.columns or not any(col in NUMERIC_FIELDS for col in frame.columns) or set(frame.columns)-canonical_columns:
        if frame.empty or len(frame.columns)==0:raise HTTPException(400,"The file has no data rows or columns")
        if len(frame)>20000 or len(frame.columns)>100:raise HTTPException(413,"Flexible imports are limited to 20,000 rows and 100 columns")
        schema=[]; rows=[]
        for col in frame.columns:
            values=frame[col]; present=values.dropna(); numeric=pd.to_numeric(values,errors="coerce")
            identifier=col.casefold() in {"id","cik","ticker","zip","postal_code"} or col.casefold().endswith(("_id","_code"))
            if not identifier and len(present)>0 and int(numeric.notna().sum())>=max(1,int(len(present)*.8)):
                kind="number"
            elif not identifier and len(present)>0 and pd.to_datetime(present,errors="coerce",dayfirst=True).notna().sum()>=max(1,int(len(present)*.8)):
                kind="date"
            else:kind="text"
            schema.append({"name":str(col),"type":kind,"non_null":int(values.notna().sum()),"distinct":int(values.nunique(dropna=True))})
        type_by_column={col["name"]:col["type"] for col in schema}
        for _,row in frame.iterrows():
            item={}
            for col in frame.columns:
                value=row[col]
                if pd.isna(value) or (isinstance(value,(int,float)) and not math.isfinite(float(value))):item[str(col)]=None
                elif type_by_column[str(col)]=="number":
                    parsed=pd.to_numeric(value,errors="coerce")
                    item[str(col)]=float(parsed) if not pd.isna(parsed) else str(value)
                elif hasattr(value,"item"):item[str(col)]=value.item()
                elif hasattr(value,"isoformat"):item[str(col)]=value.isoformat()
                else:item[str(col)]=value
            rows.append(item)
        record=FlexibleDataset(organization_id=organization_id,filename=Path(file.filename or "dataset").name,schema_json=json.dumps(schema),rows_json=json.dumps(rows,default=str),row_count=len(rows))
        db.add(record);db.commit();db.refresh(record)
        return {"job_id":record.id,"filename":record.filename,"status":"imported_flexible","kind":"flexible","total_rows":len(rows),"valid_rows":len(rows),"invalid_rows":0,"missing_values":int(frame.isna().sum().sum()),"duplicate_rows":0,"unknown_columns":[],"columns":schema,"created_at":record.created_at.isoformat()}
    allowed=set(NUMERIC_FIELDS)|{"period","organization"}; unknown=[x for x in frame.columns if x not in allowed]
    errors=[]; normalized=[]; seen=set()
    for idx,row in frame.iterrows():
        n=int(idx)+2; problem=[]; item={"period":str(row.get("period","")).strip()[:7]}
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",item["period"]):problem.append("period must use YYYY-MM")
        if item["period"] in seen:problem.append("duplicate period within file")
        seen.add(item["period"])
        for f in NUMERIC_FIELDS:
            raw=row.get(f)
            if pd.isna(raw) or raw=="":item[f]=None;continue
            try:
                number=float(raw)
                if number<0:problem.append(f"{f} cannot be negative")
                else:item[f]=number
            except (ValueError,TypeError):problem.append(f"{f} must be numeric")
        if item.get("renewable_kwh") is not None and item.get("electricity_kwh") is not None and item["renewable_kwh"]>item["electricity_kwh"]:problem.append("renewable_kwh exceeds electricity_kwh")
        if item.get("female_employees") is not None and item.get("employees") is not None and item["female_employees"]>item["employees"]:problem.append("female_employees exceeds employees")
        if item.get("male_employees") is not None and item.get("employees") is not None and item["male_employees"]>item["employees"]:problem.append("male_employees exceeds employees")
        if all(item.get(k) is not None for k in ("male_employees","female_employees","employees")) and item["male_employees"]+item["female_employees"]>item["employees"]:problem.append("male_employees plus female_employees exceeds employees")
        if item.get("independent_directors") is not None and item.get("board_members") is not None and item["independent_directors"]>item["board_members"]:problem.append("independent_directors exceeds board_members")
        if not any(item.get(f) is not None for f in NUMERIC_FIELDS):problem.append("row has no metric values")
        normalized.append(item)
        if problem:errors.append({"row":n,"period":item["period"],"errors":problem})
    duplicate_existing={r.period for r in db.query(ESGRecord.period).filter_by(organization_id=organization_id).all()}
    for i,item in enumerate(normalized):
        if item["period"] in duplicate_existing and not any(e["row"]==i+2 for e in errors):errors.append({"row":i+2,"period":item["period"],"errors":["period already exists for this organization"]})
    clean={e["row"] for e in errors}; valid=len(normalized)-len(clean)
    upload_dir=Path(os.getenv("UPLOAD_DIR","./uploads")); upload_dir.mkdir(parents=True,exist_ok=True)
    saved=upload_dir/(datetime.utcnow().strftime("%Y%m%d%H%M%S%f")+"_"+Path(file.filename or "upload").name)
    saved.write_bytes(content)
    clean_rows=[item for i,item in enumerate(normalized) if i+2 not in clean]
    clean_path=saved.with_name(saved.stem+"_cleaned.csv")
    pd.DataFrame(clean_rows,columns=["period",*NUMERIC_FIELDS]).to_csv(clean_path,index=False)
    job_status="imported_with_errors" if valid and clean else "imported" if valid else "validation_errors"
    job=UploadJob(filename=str(saved),cleaned_path=str(clean_path),organization_id=organization_id,status=job_status,total_rows=len(frame),valid_rows=valid,invalid_rows=len(clean),report_json=json.dumps(errors));db.add(job);db.flush()
    imported=[]
    for i,item in enumerate(normalized):
        if i+2 in clean:continue
        db.add(ESGRecord(organization_id=organization_id,source=f"Upload job {job.id}: {Path(file.filename or '').name}",**item));imported.append(item["period"])
    db.commit()
    return {"job_id":job.id,"filename":Path(file.filename or "upload").name,"cleaned_file":Path(clean_path).name,"status":job_status,"total_rows":len(frame),"valid_rows":valid,"invalid_rows":len(clean),"unknown_columns":unknown,"missing_values":int(frame.isna().sum().sum()),"duplicate_rows":sum(1 for e in errors if any("duplicate" in x for x in e["errors"])),"imported_periods":imported,"errors":errors}

@app.get("/api/v1/datasets/latest")
def latest_flexible_dataset(organization_id:int,db:Session=Depends(db_session)):
    item=db.query(FlexibleDataset).filter_by(organization_id=organization_id).order_by(FlexibleDataset.id.desc()).first()
    if not item:return None
    standard=db.query(UploadJob).filter_by(organization_id=organization_id).order_by(UploadJob.id.desc()).first()
    if standard and standard.created_at and item.created_at and standard.created_at>item.created_at:return None
    schema=json.loads(item.schema_json); rows=json.loads(item.rows_json)
    summaries=[]
    for col in schema:
        if col["type"]!="number":continue
        values=[r[col["name"]] for r in rows if isinstance(r.get(col["name"]),(int,float)) and not isinstance(r.get(col["name"]),bool)]
        if values:summaries.append({"name":col["name"],"mean":round(sum(values)/len(values),3),"min":min(values),"max":max(values),"count":len(values)})
    return {"id":item.id,"filename":item.filename,"row_count":item.row_count,"created_at":item.created_at.isoformat(),"columns":schema,"summaries":summaries,"rows":rows[:100]}

@app.get("/api/v1/ingestion/jobs")
def jobs(request:Request,db:Session=Depends(db_session)):
    visible=db.query(Organization.id).filter(or_(Organization.owner_id.is_(None),Organization.owner_id==request.state.user_id))
    standard=[{"id":j.id,"filename":Path(j.filename).name,"organization_id":j.organization_id,"status":j.status,"total_rows":j.total_rows,"valid_rows":j.valid_rows,"invalid_rows":j.invalid_rows,"created_at":j.created_at.isoformat()} for j in db.query(UploadJob).filter(UploadJob.organization_id.in_(visible)).order_by(UploadJob.id.desc())]
    flexible=[{"id":-j.id,"filename":j.filename,"organization_id":j.organization_id,"status":"imported_flexible","total_rows":j.row_count,"valid_rows":j.row_count,"invalid_rows":0,"created_at":j.created_at.isoformat()} for j in db.query(FlexibleDataset).filter(FlexibleDataset.organization_id.in_(visible)).order_by(FlexibleDataset.id.desc())]
    return sorted(standard+flexible,key=lambda j:j["created_at"],reverse=True)[:100]

@app.get("/api/v1/ingestion/jobs/{job_id}")
def job_detail(job_id:int,db:Session=Depends(db_session)):
    j=db.get(UploadJob,job_id)
    if not j:raise HTTPException(404,"Job not found")
    return {"id":j.id,"filename":Path(j.filename).name,"status":j.status,"total_rows":j.total_rows,"valid_rows":j.valid_rows,"invalid_rows":j.invalid_rows,"errors":json.loads(j.report_json)}

@app.get("/api/v1/ingestion/jobs/{job_id}/file")
def job_file(job_id:int,cleaned:bool=False,db:Session=Depends(db_session)):
    j=db.get(UploadJob,job_id)
    if not j:raise HTTPException(404,"Job not found")
    path=j.cleaned_path if cleaned else j.filename
    if not path or not Path(path).is_file():raise HTTPException(404,"File not found")
    return FileResponse(path,filename=Path(path).name)

@app.get("/api/v1/ingestion/jobs/{job_id}/validation-report.csv")
def validation_report(job_id:int,db:Session=Depends(db_session)):
    j=db.get(UploadJob,job_id)
    if not j:raise HTTPException(404,"Job not found")
    report=json.loads(j.report_json);out=io.StringIO();pd.DataFrame([{"row":e["row"],"period":e["period"],"errors":"; ".join(e["errors"])} for e in report],columns=["row","period","errors"]).to_csv(out,index=False)
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":f"attachment; filename=validation_{job_id}.csv"})

@app.get("/api/v1/ingestion/template")
def template():
    cols=["period",*NUMERIC_FIELDS]
    out=io.StringIO();pd.DataFrame(columns=cols).to_csv(out,index=False)
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=esg_upload_template.csv"})

@app.get("/api/v1/ingestion/sample.xlsx")
def sample_dataset():
    path=Path(__file__).resolve().parents[1]/"sample_data"/"upload_sample.xlsx"
    if not path.is_file():raise HTTPException(404,"Demonstration dataset not found")
    return FileResponse(path,filename="esg_demo_monthly.xlsx")

@app.get("/api/v1/esg/records")
def records(organization_id:int,year:int|None=None,db:Session=Depends(db_session)):
    q=db.query(ESGRecord).filter_by(organization_id=organization_id)
    if year:q=q.filter(ESGRecord.period.startswith(str(year)))
    return [{"id":r.id,"period":r.period,"source":r.source,**{f:getattr(r,f) for f in NUMERIC_FIELDS}} for r in q.order_by(ESGRecord.period)]

@app.post("/api/v1/calculations/run")
def calculate(organization_id:int,year:int|None=None,db:Session=Depends(db_session)):
    d=dashboard(db,organization_id,year)
    return {"organization_id":organization_id,"periods":d["count"],"latest_kpis":d["kpis"],"scores":d["scores"],"calculation_status":"complete" if d["count"] else "no_data"}

@app.post("/api/v1/ml/anomalies/run")
def run_anomalies(request:Request,organization_id:int,db:Session=Depends(db_session)):
    org_write_access(db,organization_id,request.state.user_id)
    rows=db.query(ESGRecord).filter_by(organization_id=organization_id).order_by(ESGRecord.period).all()
    if len(rows)<12:return {"status":"insufficient_data","message":"At least 12 monthly records are required.","count":len(rows),"anomalies":[]}
    found=find_anomalies(rows)
    for a in found:db.add(AnomalyEvent(organization_id=organization_id,**a))
    db.commit();return {"status":"complete","count":len(rows),"anomalies":found}

@app.get("/api/v1/ml/anomalies")
def anomalies(organization_id:int,db:Session=Depends(db_session)):
    return [{"id":a.id,"period":a.period,"metric":a.metric,"value":a.value,"severity":a.severity,"explanation":a.explanation,"acknowledged":a.acknowledged} for a in db.query(AnomalyEvent).filter_by(organization_id=organization_id).order_by(AnomalyEvent.period.desc())]

@app.post("/api/v1/ml/anomalies/{event_id}/acknowledge")
def acknowledge(event_id:int,request:Request,db:Session=Depends(db_session)):
    a=db.get(AnomalyEvent,event_id)
    if not a:raise HTTPException(404,"Anomaly not found")
    org_write_access(db,a.organization_id,request.state.user_id)
    a.acknowledged=True;db.commit();return {"id":a.id,"acknowledged":True}

@app.get("/api/v1/exports/data.xlsx")
def export_data(organization_id:int,db:Session=Depends(db_session)):
    rows=db.query(ESGRecord).filter_by(organization_id=organization_id).order_by(ESGRecord.period).all()
    frame=pd.DataFrame([{k:getattr(r,k) for k in ["period",*NUMERIC_FIELDS]} for r in rows]);out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as writer:frame.to_excel(writer,index=False,sheet_name="ESG Data")
    out.seek(0);return StreamingResponse(out,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=esg_data.xlsx"})

@app.post("/api/v1/reports/generate")
def report(organization_id:int,year:int|None=None,db:Session=Depends(db_session)):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    org=db.get(Organization,organization_id)
    if not org:raise HTTPException(404,"Organization not found")
    data=dashboard(db,organization_id,year);obs=insights(data);recs=recommendations(data)
    out=io.BytesIO();c=canvas.Canvas(out,pagesize=letter);w,h=letter;y=h-48
    c.setFont("Helvetica-Bold",18);c.drawString(42,y,"ESG Intelligence | Analytical Summary");y-=28
    c.setFont("Helvetica",10);c.drawString(42,y,f"{org.name} | {org.industry} | Period: {year or 'all available'} | Synthetic records are illustrative");y-=28
    c.setFont("Helvetica-Bold",12);c.drawString(42,y,"Latest reporting period KPIs");y-=18;c.setFont("Helvetica",10)
    for k in data["kpis"]:
        value="Not available" if k["value"] is None else f"{k['value']:.2f} {k['unit']}"
        c.drawString(48,y,f"{k['name']}: {value}");y-=15
    y-=8;c.setFont("Helvetica-Bold",12);c.drawString(42,y,"Illustrative ESG scores");y-=18;c.setFont("Helvetica",10)
    for key in ("environmental","social","governance","overall"):
        c.drawString(48,y,f"{key.title()}: {data['scores'][key] if data['scores'][key] is not None else 'Not available'}");y-=15
    sector=benchmarking(organization_id,year,db)
    y-=8;c.setFont("Helvetica-Bold",12);c.drawString(42,y,"Illustrative sector benchmark comparison");y-=18;c.setFont("Helvetica",9)
    c.drawString(48,y,sector["label"]);y-=15
    for item in sector["items"]:
        if item["organization"] is not None:
            c.drawString(48,y,f"{item['metric']}: organization {item['organization']:.5g} vs reference {item['benchmark']:.5g} {item['unit']} ({item['performance']})");y-=13
    events=db.query(AnomalyEvent).filter_by(organization_id=organization_id).order_by(AnomalyEvent.period.desc()).limit(5).all()
    if events:
        y-=8;c.setFont("Helvetica-Bold",12);c.drawString(42,y,"Recent anomaly review signals");y-=18;c.setFont("Helvetica",9)
        for event in events:
            c.drawString(48,y,f"{event.period} | {event.metric} | {event.severity} | {'Reviewed' if event.acknowledged else 'Open'}");y-=13
    y-=8;c.setFont("Helvetica-Bold",12);c.drawString(42,y,"Observations and actions");y-=18;c.setFont("Helvetica",9)
    for item in (obs+recs)[:10]:
        line=item.get("detail") or item.get("action","")
        c.drawString(48,y,(item.get("title") or item.get("issue", ""))[:95]);y-=13
        c.drawString(58,y,line[:100]);y-=17
        if y<60:c.showPage();y=h-48;c.setFont("Helvetica",9)
    c.save();out.seek(0)
    return StreamingResponse(out,media_type="application/pdf",headers={"Content-Disposition":"attachment; filename=esg_report.pdf"})
