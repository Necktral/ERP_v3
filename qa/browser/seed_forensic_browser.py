"""Fixtures determinísticos exclusivos del stack browser forense."""
import os

if os.getenv("FORENSIC_BROWSER_SEED") != "1":
    raise SystemExit("Refusing seed: FORENSIC_BROWSER_SEED=1 is required")

from django.contrib.auth import get_user_model
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Role, RoleAssignment

User = get_user_model()
company = OrgUnit.objects.get(code="FORENSIC-CO")
branch = OrgUnit.objects.get(code="FORENSIC-BR")
password = os.environ.get("FORENSIC_E2E_PASSWORD")
if not password:
    raise SystemExit("Refusing seed: FORENSIC_E2E_PASSWORD is required")

for username, role_name in (("forensic_contador", "accountant"), ("forensic_cajero", "cashier")):
    user, _ = User.objects.get_or_create(username=username, defaults={"email": f"{username}@forensic.invalid"})
    user.is_active = True
    user.set_password(password)
    user.save(update_fields=["password", "is_active"])
    for unit in (company, branch):
        UserMembership.objects.update_or_create(user=user, org_unit=unit, defaults={"is_active": True})
    role = Role.objects.get(name=role_name)
    role_scopes = (company, branch) if role_name == "cashier" else (company,)
    for scope in role_scopes:
        RoleAssignment.objects.update_or_create(
            user=user, role=role, org_unit=scope, origin=RoleAssignment.Origin.SYSTEM,
            defaults={"is_active": True, "origin_ref": "forensic-browser"},
        )
print("forensic browser roles seeded")
