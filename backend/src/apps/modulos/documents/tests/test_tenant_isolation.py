from __future__ import annotations

import base64
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.modulos.documents.models import ScannedDocument
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission


def _scope(label: str):
    holding = OrgUnit.objects.create(unit_type="HOLDING", name=f"H-{label}")
    company = OrgUnit.objects.create(unit_type="COMPANY", parent=holding, name=f"C-{label}")
    branch = OrgUnit.objects.create(unit_type="BRANCH", parent=company, name=f"B-{label}")
    return company, branch


def _client(company, branch):
    User = get_user_model()
    name = f"docs_{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(username=name, password="pass12345")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    role = Role.objects.create(name=f"docs_role_{uuid.uuid4().hex[:8]}")
    permission, _ = Permission.objects.get_or_create(
        code="documents.scan.create", defaults={"description": "create", "is_active": True}
    )
    RolePermission.objects.create(role=role, permission=permission)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    client = APIClient()
    login = client.post("/api/auth/login/", {"username": name, "password": "pass12345"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client


@pytest.mark.django_db
def test_upload_rejects_branch_from_another_company():
    company_a, branch_a = _scope("A")
    _company_b, branch_b = _scope("B")
    client = _client(company_a, branch_a)

    response = client.post(
        "/api/documents/scans/upload/",
        {
            "doc_type": "GENERAL",
            "content_type": "image/png",
            "image_base64": base64.b64encode(b"image").decode(),
            "branch_id": branch_b.id,
        },
        format="json",
    )

    assert response.status_code == 422, response.data
    assert ScannedDocument.objects.count() == 0
