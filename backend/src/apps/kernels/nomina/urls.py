from __future__ import annotations

from django.urls import path

from .field import views_field as field_capture_views
from .views import (
    HealthView,
    IRBracketView,
    NominaConfigDetailView,
    NominaConfigView,
    PaySummaryView,
    PayrollEntryDailyAttendanceView,
    PayrollEntryDetailView,
    PayrollEntryView,
    PayrollPaymentView,
    PayrollPeriodView,
    PayrollSheetActionView,
    PayrollSheetPdfView,
    PayrollSheetView,
    PayrollSheetXlsxView,
)
from .views_field import (
    FieldApplyToSheetView,
    FieldApprovalApproveView,
    FieldApprovalRequestView,
    FieldConsolidateView,
    FieldConsolidationListView,
    FieldCrewReportView,
    FieldCrewView,
    FieldRollCallView,
    FieldTransferView,
    FieldWorkDayDetailView,
    FieldWorkDayView,
    FieldWorkerEventView,
)
from .views_inss import (
    EmployeeInssEnrollmentView,
    PeriodInssClassifyView,
    PeriodInssElectionView,
    PeriodInssResolveView,
)
from .views_complement import (
    ComplementLineView,
    ComplementReciboPdfView,
    ComplementSheetActionView,
    ComplementSheetDetailView,
    ComplementSheetView,
)
from .views_asistencia import AsistenciaHoyView
from .biometric.views_biometric import (
    BiometricBatchListView,
    BiometricCheckListView,
    BiometricDeviceDetailView,
    BiometricDeviceListCreateView,
    BiometricDeviceRotateTokenView,
    BiometricImportView,
    BiometricMapView,
    BiometricPushView,
    BiometricRollupView,
)

urlpatterns = [
    path("health/", HealthView.as_view()),
    # Asistencia del día (pantalla simple del mandador/capataz — PC y cel)
    path("asistencia/hoy/", AsistenciaHoyView.as_view()),
    # Control biométrico (fuente ① de asistencia)
    path("biometric/devices/", BiometricDeviceListCreateView.as_view()),
    path("biometric/devices/<int:device_pk>/", BiometricDeviceDetailView.as_view()),
    path("biometric/devices/<int:device_pk>/rotate-token/", BiometricDeviceRotateTokenView.as_view()),
    path("biometric/devices/<int:device_pk>/import/", BiometricImportView.as_view()),
    path("biometric/batches/", BiometricBatchListView.as_view()),
    path("biometric/checks/", BiometricCheckListView.as_view()),
    path("biometric/map/", BiometricMapView.as_view()),
    path("biometric/rollup/", BiometricRollupView.as_view()),
    path("biometric/push/", BiometricPushView.as_view()),
    # Configuración de tasas
    path("config/", NominaConfigView.as_view()),
    path("config/<int:config_id>/", NominaConfigDetailView.as_view()),
    path("config/<int:config_id>/ir-brackets/", IRBracketView.as_view()),
    # Períodos (quincenas)
    path("periods/", PayrollPeriodView.as_view()),
    # Sala de pago — resumen consolidado por empleado (app del pagador)
    path("periods/<int:period_id>/pay-summary/", PaySummaryView.as_view()),
    # Planillas por período
    path("periods/<int:period_id>/sheets/", PayrollSheetView.as_view()),
    # Export legal (xlsx) — antes de la ruta de acción para no colisionar
    path("periods/<int:period_id>/sheets/<int:sheet_id>/planilla.xlsx", PayrollSheetXlsxView.as_view()),
    path("periods/<int:period_id>/sheets/<int:sheet_id>/planilla.pdf", PayrollSheetPdfView.as_view()),
    # Entradas por planilla — ANTES de <str:action> (que si no, atrapa "entries"
    # como acción y exige nomina.sheet.manage en vez de nomina.entry.*)
    path("periods/<int:period_id>/sheets/<int:sheet_id>/entries/", PayrollEntryView.as_view()),
    # Registrar el pago del neto de una línea (app del pagador) — ANTES de <str:action>
    path(
        "periods/<int:period_id>/sheets/<int:sheet_id>/entries/<int:entry_id>/pay/",
        PayrollPaymentView.as_view(),
    ),
    # Captura de asistencia día-por-día de una línea (planilla fiel) — ANTES de la genérica
    path(
        "periods/<int:period_id>/sheets/<int:sheet_id>/entries/<int:entry_id>/daily-attendance/",
        PayrollEntryDailyAttendanceView.as_view(),
    ),
    # Editar / quitar una línea (PATCH/DELETE) — tras /pay/ para no atraparlo
    path(
        "periods/<int:period_id>/sheets/<int:sheet_id>/entries/<int:entry_id>/",
        PayrollEntryDetailView.as_view(),
    ),
    path("periods/<int:period_id>/sheets/<int:sheet_id>/<str:action>/", PayrollSheetActionView.as_view()),
    # Complemento de salario (planilla replicada, bruto en recibo) — rutas específicas
    # ANTES de la genérica <str:action> para que ganen.
    path("periods/<int:period_id>/complement-sheets/", ComplementSheetView.as_view()),
    path("periods/<int:period_id>/complement-sheets/<int:sheet_id>/", ComplementSheetDetailView.as_view()),
    path("periods/<int:period_id>/complement-sheets/<int:sheet_id>/recibo.pdf", ComplementReciboPdfView.as_view()),
    path("periods/<int:period_id>/complement-sheets/<int:sheet_id>/lines/<int:line_id>/", ComplementLineView.as_view()),
    path("periods/<int:period_id>/complement-sheets/<int:sheet_id>/<str:action>/", ComplementSheetActionView.as_view()),
    # Asistencia de campo — flujo diario
    path("field/work-days/", FieldWorkDayView.as_view()),
    path("field/work-days/<int:work_day_id>/", FieldWorkDayDetailView.as_view()),
    path("field/work-days/<int:work_day_id>/rollcall/", FieldRollCallView.as_view()),
    path("field/work-days/<int:work_day_id>/crews/", FieldCrewView.as_view()),
    path("field/work-days/<int:work_day_id>/events/", FieldWorkerEventView.as_view()),
    path("field/work-days/<int:work_day_id>/transfers/", FieldTransferView.as_view()),
    path("field/work-days/<int:work_day_id>/consolidate/", FieldConsolidateView.as_view()),
    path("field/work-days/<int:work_day_id>/consolidations/", FieldConsolidationListView.as_view()),
    # Aprobación SoD (maker-checker): solicitar → aprobar (approver != maker)
    path("field/work-days/<int:work_day_id>/approve-request/", FieldApprovalRequestView.as_view()),
    path("field/approval-requests/", FieldApprovalRequestView.as_view()),
    path("field/approvals/<uuid:request_id>/approve/", FieldApprovalApproveView.as_view()),
    path("field/crews/<int:crew_id>/report/", FieldCrewReportView.as_view()),
    path("field/sheets/<int:sheet_id>/apply-field-attendance/", FieldApplyToSheetView.as_view()),
    # Régimen INSS — afiliación fechada + elección por período
    path("inss/employees/<int:employee_id>/enrollments/", EmployeeInssEnrollmentView.as_view()),
    path("periods/<int:period_id>/inss/elections/", PeriodInssElectionView.as_view()),
    path("periods/<int:period_id>/inss/resolve/", PeriodInssResolveView.as_view()),
    path("periods/<int:period_id>/inss/classify/", PeriodInssClassifyView.as_view()),
    # Asistencia de campo — captura por cuadrilla (PR #17)
    path("field/crews/", field_capture_views.FieldCaptureCrewView.as_view()),
    path("field/capture/work-days/", field_capture_views.FieldCaptureWorkDayView.as_view()),
    path("field/reports/<int:report_id>/events/", field_capture_views.FieldCaptureEventView.as_view()),
    path("field/reports/<int:report_id>/approve/request/", field_capture_views.FieldReportApprovalRequestView.as_view()),
    path("field/reports/<int:report_id>/approve/", field_capture_views.FieldReportApproveView.as_view()),
    path("field/reports/<int:report_id>/build-attendance/", field_capture_views.FieldReportBuildAttendanceView.as_view()),
]
