from types import SimpleNamespace

import pytest
from django.core.cache import caches

from apps.kernels.reporting import execution
from apps.kernels.reporting.execution import ResolvedReportScope
from apps.kernels.reporting.lineage import build_lineage
from apps.kernels.reporting.registry import DATASET_REGISTRY, get_dataset_spec
from apps.modulos.iam.models import OrgUnit


def test_adapter_cache_isolated_by_company_branch_and_filters(monkeypatch):
    spec = get_dataset_spec("billing.summary.period")
    company_a = SimpleNamespace(id=101)
    company_b = SimpleNamespace(id=202)
    branch_a = SimpleNamespace(id=11)
    branch_b = SimpleNamespace(id=22)
    calls: list[tuple[int, int, tuple[tuple[str, str], ...]]] = []

    def adapter(*, spec, scope, filters):
        marker = (
            scope.company.id,
            scope.branch.id,
            tuple(sorted((str(key), str(value)) for key, value in filters.items())),
        )
        calls.append(marker)
        return {"rows": [{"marker": repr(marker)}]}

    monkeypatch.setattr(execution, "_adapter_run", adapter)
    caches["catalogs"].clear()
    scope_a = ResolvedReportScope(company_a, branch_a, "BRANCH", "test")
    filters_a = {"date_from": "2026-01-01", "date_to": "2026-01-31"}

    first = execution._adapter_run_cached(spec=spec, scope=scope_a, filters=filters_a, force_refresh=False)
    first["rows"][0]["marker"] = "mutado"
    replay = execution._adapter_run_cached(
        spec=spec,
        scope=scope_a,
        filters={"date_to": "2026-01-31", "date_from": "2026-01-01"},
        force_refresh=False,
    )
    execution._adapter_run_cached(
        spec=spec,
        scope=ResolvedReportScope(company_b, branch_a, "BRANCH", "test"),
        filters=filters_a,
        force_refresh=False,
    )
    execution._adapter_run_cached(
        spec=spec,
        scope=ResolvedReportScope(company_a, branch_b, "BRANCH", "test"),
        filters=filters_a,
        force_refresh=False,
    )
    execution._adapter_run_cached(
        spec=spec,
        scope=scope_a,
        filters={"date_from": "2026-02-01", "date_to": "2026-02-28"},
        force_refresh=False,
    )

    assert replay["rows"][0]["marker"] != "mutado"
    assert len(calls) == 4


@pytest.mark.django_db
def test_every_registry_dataset_dispatches_with_complete_adapter_lineage():
    holding = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.HOLDING, name="Lineage Holding")
    company = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.COMPANY, name="Lineage Company", parent=holding)
    branch = OrgUnit.objects.create(unit_type=OrgUnit.UnitType.BRANCH, name="Lineage Branch", parent=company)
    scope = ResolvedReportScope(company, branch, "BRANCH", "test")

    for spec in DATASET_REGISTRY:
        filters = {}
        for name, rule in spec.filters_schema.items():
            if not rule.get("required"):
                continue
            filters[name] = {"int": 2026, "date": "2026-01-31", "str": "1000"}.get(rule.get("type"), "x")
        payload = execution._adapter_run(spec=spec, scope=scope, filters=filters)
        source_modules = list((payload.get("source_summary") or {}).get("source_modules") or [])
        assert source_modules, spec.dataset_key
        lineage = build_lineage(
            run_id="lineage-run",
            dataset_key=spec.dataset_key,
            source_modules=source_modules,
            semantic_version=spec.semantic_version,
            schema_version=spec.schema_version,
        )
        assert lineage == {
            "run_id": "lineage-run",
            "dataset_key": spec.dataset_key,
            "source_modules": source_modules,
            "semantic_version": spec.semantic_version,
            "schema_version": spec.schema_version,
        }

