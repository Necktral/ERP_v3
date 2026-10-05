import pytest
from django.test import override_settings

from apps.kernels.reporting.enums import ExportStatus, RunStatus
from apps.kernels.reporting.exceptions import ReportingValidationError
from apps.kernels.reporting.exports import create_export_from_run
from apps.kernels.reporting.models import ReportExportLog, ReportRun


def _run_with_rows(rows, *, formats=("json", "csv", "xlsx")):
    return ReportRun.objects.create(
        dataset_key="test.export.limits",
        status=RunStatus.SUCCEEDED,
        row_count=len(rows),
        result_payload_json={
            "rows": rows,
            "dimensions": ["id", "name"],
            "measures": ["amount"],
            "export_capabilities": list(formats),
        },
    )


@pytest.mark.django_db
@pytest.mark.parametrize("export_format", ["json", "csv", "xlsx"])
@override_settings(
    REPORTING_EXPORT_MAX_ROWS=2,
    REPORTING_EXPORT_MAX_CELLS=100,
    REPORTING_EXPORT_MAX_OUTPUT_BYTES=1_000_000,
)
def test_export_rejects_row_budget_before_render_without_partial_content(export_format):
    run = _run_with_rows([{"id": i, "name": "fila", "amount": "1.00"} for i in range(3)])
    with pytest.raises(ReportingValidationError, match="límite de filas"):
        create_export_from_run(run=run, requested_by=None, export_format=export_format)

    export = ReportExportLog.objects.get(run=run)
    assert export.status == ExportStatus.FAILED
    assert export.content_text == ""
    assert export.content_base64 == ""
    assert export.file_size == 0


@pytest.mark.django_db
@override_settings(
    REPORTING_EXPORT_MAX_ROWS=10,
    REPORTING_EXPORT_MAX_CELLS=5,
    REPORTING_EXPORT_MAX_OUTPUT_BYTES=1_000_000,
)
def test_export_rejects_cell_budget_before_render():
    run = _run_with_rows([{"id": 1, "name": "a", "amount": "1", "extra": "x"}] * 2)
    with pytest.raises(ReportingValidationError, match="límite de celdas"):
        create_export_from_run(run=run, requested_by=None, export_format="csv")
    assert ReportExportLog.objects.get(run=run).status == ExportStatus.FAILED


@pytest.mark.django_db
@pytest.mark.parametrize("export_format", ["json", "csv", "xlsx"])
@override_settings(
    REPORTING_EXPORT_MAX_ROWS=10,
    REPORTING_EXPORT_MAX_CELLS=100,
    REPORTING_EXPORT_MAX_CELL_BYTES=64,
    REPORTING_EXPORT_MAX_INPUT_BYTES=10_000,
    REPORTING_EXPORT_MAX_OUTPUT_BYTES=1_000_000,
)
def test_export_rejects_giant_cell_before_render(export_format):
    run = _run_with_rows([{"id": 1, "name": "x" * 65, "amount": "1.00"}])
    with pytest.raises(ReportingValidationError, match="celda que excede"):
        create_export_from_run(run=run, requested_by=None, export_format=export_format)
    export = ReportExportLog.objects.get(run=run)
    assert export.status == ExportStatus.FAILED
    assert export.content_text == ""
    assert export.content_base64 == ""


@pytest.mark.django_db
@override_settings(
    REPORTING_EXPORT_MAX_ROWS=10,
    REPORTING_EXPORT_MAX_CELLS=100,
    REPORTING_EXPORT_MAX_CELL_BYTES=100,
    REPORTING_EXPORT_MAX_INPUT_BYTES=20,
    REPORTING_EXPORT_MAX_OUTPUT_BYTES=1_000_000,
)
def test_export_rejects_cumulative_input_budget_before_render():
    run = _run_with_rows([{"id": 1, "name": "abcdefghij", "amount": "1.00"}])
    with pytest.raises(ReportingValidationError, match="presupuesto de entrada"):
        create_export_from_run(run=run, requested_by=None, export_format="csv")
    assert ReportExportLog.objects.get(run=run).status == ExportStatus.FAILED


@pytest.mark.django_db
@pytest.mark.parametrize("export_format", ["json", "csv", "xlsx"])
@override_settings(
    REPORTING_EXPORT_MAX_ROWS=10,
    REPORTING_EXPORT_MAX_CELLS=100,
    REPORTING_EXPORT_MAX_OUTPUT_BYTES=32,
)
def test_export_rejects_output_byte_budget_without_persisting_binary(export_format):
    run = _run_with_rows([{"id": 1, "name": "x" * 200, "amount": "1.00"}])
    with pytest.raises(ReportingValidationError, match="límite de tamaño"):
        create_export_from_run(run=run, requested_by=None, export_format=export_format)
    export = ReportExportLog.objects.get(run=run)
    assert export.status == ExportStatus.FAILED
    assert export.content_text == ""
    assert export.content_base64 == ""
    assert export.file_size == 0


@pytest.mark.django_db
@pytest.mark.parametrize("export_format", ["json", "csv", "xlsx"])
@override_settings(
    REPORTING_EXPORT_MAX_ROWS=250,
    REPORTING_EXPORT_MAX_CELLS=1000,
    REPORTING_EXPORT_MAX_OUTPUT_BYTES=2_000_000,
)
def test_export_at_large_boundary_stays_within_budget(export_format):
    rows = [{"id": i, "name": f"fila-{i}", "amount": "1.00"} for i in range(250)]
    export = create_export_from_run(
        run=_run_with_rows(rows),
        requested_by=None,
        export_format=export_format,
    )
    assert export.status == ExportStatus.SUCCEEDED
    assert 0 < export.file_size <= 2_000_000
