from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db import Base
from app.main import RegisterBody, LoginBody, ProfileBody, OrganizationBody, register, login, get_profile, update_profile, create_organization, update_organization, overview, decode_token, hash_password, verify_password
from app.models import ESGRecord

def test_register_login_profile_and_owned_organization_reflect_updates():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        body=RegisterBody(email="demo@example.com",full_name="Demo User",password="correct-horse-7")
        created=register(body,db)
        assert created["user"]["full_name"]=="Demo User"
        assert decode_token(created["access_token"])==created["user"]["id"]
        user=login(LoginBody(email="demo@example.com",password="correct-horse-7"),db)
        assert user["user"]["email"]=="demo@example.com"
        request=SimpleNamespace(state=SimpleNamespace(user_id=user["user"]["id"]))
        updated=update_profile(ProfileBody(full_name="Updated User",email="updated@example.com"),request,db)
        assert updated["full_name"]=="Updated User"
        assert get_profile(request,db)["email"]=="updated@example.com"
        org=create_organization(OrganizationBody(name="Northstar Energy",industry="Energy"),request,db)
        assert org["owned"] is True and org["name"]=="Northstar Energy"
        db.add(ESGRecord(organization_id=org["id"],period="2026-01",scope1_tco2e=2,scope2_tco2e=3,scope3_tco2e=4))
        db.commit()
        updated_org=update_organization(org["id"],OrganizationBody(name="Northstar Renewables",industry="Energy"),request,db)
        assert updated_org["name"]=="Northstar Renewables"
        assert overview(org["id"],None,db)["count"]==1
    engine.dispose()

def test_passwords_are_salted_and_verified():
    first=hash_password("a-long-password")
    second=hash_password("a-long-password")
    assert first!=second
    assert verify_password("a-long-password",first)
    assert not verify_password("wrong-password",first)
