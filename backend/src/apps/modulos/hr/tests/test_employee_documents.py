"""Tests del expediente documental (Ola F): validación por bytes, tamaño, CRUD,
RBAC del endpoint y que el perfil incluya documentos + saldo de vacaciones."""
from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.modulos.hr.document_service import (
    MAX_UPLOAD_BYTES,
    attach_employee_document,
    list_employee_documents,
    remove_employee_document,
)
from apps.modulos.hr.models import Employee, EmployeeDocument
from apps.modulos.iam.models import OrgUnit, UserMembership
from apps.modulos.rbac.models import Permission, Role, RoleAssignment, RolePermission

User = get_user_model()
UT = OrgUnit.UnitType

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 40
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def _mk_org():
    s = uuid.uuid4().hex[:6]
    holding = OrgUnit.objects.create(unit_type=UT.HOLDING, name=f"H_{s}")
    company = OrgUnit.objects.create(unit_type=UT.COMPANY, name=f"C_{s}", parent=holding)
    branch = OrgUnit.objects.create(unit_type=UT.BRANCH, name=f"B_{s}", parent=company)
    return holding, company, branch


def _mk_user(prefix="hr"):
    u = f"{prefix}_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=u, email=f"{u}@t.local", password="pass12345")


def _mk_employee(company):
    return Employee.objects.create(company=company, first_name="Rosa", last_name="Díaz")


def _client_with_perms(*, company, branch, perm_codes):
    user = _mk_user("api")
    UserMembership.objects.create(user=user, org_unit=company, is_active=True)
    UserMembership.objects.create(user=user, org_unit=branch, is_active=True)
    role = Role.objects.create(name=f"role_{uuid.uuid4().hex[:8]}", is_active=True)
    for code in perm_codes:
        perm, _ = Permission.objects.get_or_create(code=code, defaults={"description": code, "is_active": True})
        RolePermission.objects.get_or_create(role=role, permission=perm)
    RoleAssignment.objects.create(user=user, role=role, org_unit=company, is_active=True)
    RoleAssignment.objects.create(user=user, role=role, org_unit=branch, is_active=True)

    client = APIClient()
    login = client.post("/api/auth/login/", {"username": user.username, "password": "pass12345"}, format="json")
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data.get('access')}")
    client.defaults["HTTP_X_COMPANY_ID"] = str(company.id)
    client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("raw,ctype", [(PDF_BYTES, "application/pdf"), (JPEG_BYTES, "image/jpeg"), (PNG_BYTES, "image/png")])
def test_attach_valid_formats(raw, ctype):
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    doc = attach_employee_document(
        request=None, actor=_mk_user(), employee=emp, raw=raw,
        category=EmployeeDocument.Category.CEDULA, title="Cédula", filename="ced.pdf",
    )
    assert doc.content_type == ctype
    assert doc.byte_size == len(raw)
    assert doc.category == EmployeeDocument.Category.CEDULA


@pytest.mark.django_db
def test_attach_invalid_bytes_rejected():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    with pytest.raises(ValidationError):
        attach_employee_document(
            request=None, actor=_mk_user(), employee=emp, raw=b"esto no es un archivo valido",
            category=EmployeeDocument.Category.OTRO, title="x",
        )


@pytest.mark.django_db
def test_attach_oversize_rejected():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    big = PDF_BYTES + b"0" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(ValidationError):
        attach_employee_document(
            request=None, actor=_mk_user(), employee=emp, raw=big,
            category=EmployeeDocument.Category.OTRO, title="grande",
        )


@pytest.mark.django_db
def test_attach_invalid_category_rejected():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    with pytest.raises(ValidationError):
        attach_employee_document(
            request=None, actor=_mk_user(), employee=emp, raw=PDF_BYTES,
            category="NO_EXISTE", title="x",
        )


@pytest.mark.django_db
def test_list_and_remove():
    _, company, _ = _mk_org()
    emp = _mk_employee(company)
    actor = _mk_user()
    doc = attach_employee_document(
        request=None, actor=actor, employee=emp, raw=PDF_BYTES,
        category=EmployeeDocument.Category.INSS, title="INSS",
    )
    assert len(list_employee_documents(emp)) == 1
    assert remove_employee_document(request=None, actor=actor, doc=doc) is True
    assert list_employee_documents(emp) == []


@pytest.mark.django_db
def test_api_upload_requires_manage_permission():
    _, company, branch = _mk_org()
    emp = _mk_employee(company)
    client = _client_with_perms(company=company, branch=branch, perm_codes=["hr.file.read"])
    upload = SimpleUploadedFile("ced.pdf", PDF_BYTES, content_type="application/pdf")
    resp = client.post(
        f"/api/hr/employees/{emp.id}/documents/",
        {"file": upload, "category": "CEDULA", "title": "Cédula"},
        format="multipart",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_api_upload_and_profile_includes_documents_and_balance():
    _, company, branch = _mk_org()
    emp = _mk_employee(company)
    client = _client_with_perms(
        company=company, branch=branch,
        perm_codes=["hr.file.manage", "hr.file.read", "hr.employee.read"],
    )
    upload = SimpleUploadedFile("titulo.pdf", PDF_BYTES, content_type="application/pdf")
    resp = client.post(
        f"/api/hr/employees/{emp.id}/documents/",
        {"file": upload, "category": "TITULO", "title": "Bachiller"},
        format="multipart",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["category"] == "TITULO"

    profile = client.get(f"/api/hr/employees/{emp.id}/profile/")
    assert profile.status_code == 200
    assert "documents" in profile.data
    assert len(profile.data["documents"]) == 1
    assert "vacation_balance" in profile.data
