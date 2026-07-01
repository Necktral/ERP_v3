from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.modulos.iam.models import OrgUnit
from apps.modulos.rbac.models import Role


class JobPosition(models.Model):
    company = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="job_positions")
    code = models.CharField(max_length=64, blank=True, default="")
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hr"
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="uq_position_company_name"),
        ]
        indexes = [
            models.Index(fields=["company", "is_active"]),
        ]


class PositionRoleMap(models.Model):
    """
    Mapeo Puesto -> Role (automatización controlada).
    """

    class ScopeMode(models.TextChoices):
        COMPANY = "COMPANY", "Company"
        BRANCH = "BRANCH", "Branch"

    position = models.ForeignKey(JobPosition, on_delete=models.CASCADE, related_name="role_maps")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="position_maps")
    scope_mode = models.CharField(max_length=16, choices=ScopeMode.choices, default=ScopeMode.BRANCH)
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "hr"
        constraints = [
            models.UniqueConstraint(fields=["position", "role", "scope_mode"], name="uq_position_role_scope"),
        ]


class Employee(models.Model):
    class EmploymentStatus(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        SUSPENDIDO = "SUSPENDIDO", "Suspendido"
        BAJA = "BAJA", "Baja"

    company = models.ForeignKey(OrgUnit, on_delete=models.PROTECT, related_name="employees")
    party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="employee_records",
    )
    class Gender(models.TextChoices):
        MASCULINO = "M", "Masculino"
        FEMENINO = "F", "Femenino"

    class SalaryType(models.TextChoices):
        DAILY = "DAILY", "Por día (jornal)"
        MONTHLY = "MONTHLY", "Mensual"

    employee_code = models.CharField(max_length=64, blank=True, default="")
    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120, blank=True, default="")
    phone = models.CharField(max_length=64, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    # Datos de planilla (casillas legales): el expediente es la FUENTE y la
    # nómina los copia al crear la entrada (PayrollEntry congela el snapshot).
    cedula = models.CharField(max_length=20, blank=True, default="")
    inss_number = models.CharField(max_length=20, blank=True, default="")
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True, default="")
    salary_type = models.CharField(max_length=10, choices=SalaryType.choices, default=SalaryType.DAILY)
    daily_rate_nio = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
        help_text="Jornal diario C$ (si salary_type=DAILY)",
    )
    monthly_salary_nio = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
        help_text="Salario mensual C$ (si salary_type=MONTHLY)",
    )
    # Complemento de salario (convenio personal interno): pago bruto pactado al margen de la
    # planilla legal, que se paga en recibo aparte (sin INSS/IR). La planilla de complemento
    # (kernel nomina) toma este monto como base, ajustable por periodo.
    salary_complement_enabled = models.BooleanField(
        default=False, help_text="El trabajador tiene un complemento de salario pactado."
    )
    salary_complement_base_nio = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
        help_text="Monto base C$ del complemento acordado (bruto, sin deducciones).",
    )
    is_active = models.BooleanField(default=True)
    employment_status = models.CharField(
        max_length=16, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVO
    )
    linked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employee_links",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hr"
        indexes = [
            models.Index(fields=["company", "is_active"]),
            models.Index(fields=["company", "employment_status"]),
            models.Index(fields=["linked_user"]),
            models.Index(fields=["company", "party"], name="hr_employee_company_party_idx"),
        ]

    def clean(self):
        super().clean()
        if self.party_id and self.company_id and self.party.company_id != self.company_id:
            raise ValidationError({"party": "Employee.party debe pertenecer a Employee.company."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class EmployeePhoto(models.Model):
    """Foto del trabajador (expediente). Una por trabajador.

    Mismo patrón de almacenamiento que documents.ScannedDocument: en la DB
    (base64) — todo el expediente viaja junto en respaldos/sync. La imagen se
    normaliza al subirla (JPEG, máx. 512px) así que pesa ~30-80 KB.
    """

    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="photo")
    image_data = models.TextField()  # base64 del JPEG normalizado
    content_type = models.CharField(max_length=64, default="image/jpeg")
    byte_size = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hr_photos_updated",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hr"


class EmployeeRoleMap(models.Model):
    """Roles asignados DIRECTAMENTE a un trabajador (no vía puesto).

    Precedente: el dueño pidió un modelo centrado en el trabajador — cada persona
    lleva sus propios roles, editables desde su ficha. Scope = empresa (el rol aplica
    para el trabajador en su company). La reconciliación los materializa como
    RoleAssignment cuando el trabajador tiene usuario provisionado.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="role_maps")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="employee_maps")
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "hr"
        constraints = [
            models.UniqueConstraint(fields=["employee", "role"], name="uq_employee_role"),
        ]
        indexes = [
            models.Index(fields=["employee", "is_active"]),
        ]


class EmployeeLifecycleEvent(models.Model):
    """Bitácora del ciclo de vida laboral: suspensiones, reintegros, bajas y reingresos.

    Precedente: el estado laboral (Employee.employment_status) NUNCA se edita directo;
    solo cambia a través de estos eventos (servicios), que quedan auditados y con motivo.
    """

    class EventType(models.TextChoices):
        SUSPENSION = "SUSPENSION", "Suspensión"
        REINTEGRO = "REINTEGRO", "Reintegro"
        BAJA = "BAJA", "Baja"
        REINGRESO = "REINGRESO", "Reingreso"

    class BajaReason(models.TextChoices):
        RENUNCIA = "RENUNCIA", "Renuncia voluntaria"
        DESPIDO_JUSTIFICADO = "DESPIDO_JUSTIFICADO", "Despido con causa justificada"
        MUTUO_ACUERDO = "MUTUO_ACUERDO", "Mutuo acuerdo"
        FIN_CONTRATO = "FIN_CONTRATO", "Fin de contrato / temporada"
        ABANDONO = "ABANDONO", "Abandono de labores"
        FALLECIMIENTO = "FALLECIMIENTO", "Fallecimiento"
        OTRO = "OTRO", "Otro"

    class SuspensionReason(models.TextChoices):
        DISCIPLINARIA = "DISCIPLINARIA", "Disciplinaria"
        MEDICA = "MEDICA", "Médica / subsidio"
        PERMISO_SIN_GOCE = "PERMISO_SIN_GOCE", "Permiso sin goce de salario"
        INVESTIGACION = "INVESTIGACION", "Investigación interna"
        OTRO = "OTRO", "Otro"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="lifecycle_events")
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    reason_code = models.CharField(max_length=32, blank=True, default="")
    reason_detail = models.TextField(blank=True, default="")
    effective_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)  # fin previsto (suspensiones)
    with_pay = models.BooleanField(default=False)  # suspensión con goce de salario
    access_suspended = models.BooleanField(default=False)  # si se bloqueó el login del usuario
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hr_lifecycle_events_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "hr"
        indexes = [
            models.Index(fields=["employee", "created_at"]),
            models.Index(fields=["employee", "event_type"]),
        ]
        ordering = ["-created_at", "-id"]


class EmploymentContract(models.Model):
    """Contrato laboral redactado por caso (plantilla por tipo + texto editable).

    El texto (body) se genera desde plantilla al crear el borrador y es editable
    mientras esté en BORRADOR. Al EMITIR queda congelado (solo se puede ANULAR).
    """

    class ContractType(models.TextChoices):
        INDEFINIDO = "INDEFINIDO", "Tiempo indefinido"
        PLAZO_FIJO = "PLAZO_FIJO", "Plazo fijo / determinado"
        OBRA = "OBRA", "Por obra o servicio determinado"
        TEMPORADA = "TEMPORADA", "Por temporada (cosecha)"
        PRUEBA = "PRUEBA", "Período de prueba"
        PARCIAL = "PARCIAL", "Tiempo parcial"
        APRENDIZAJE = "APRENDIZAJE", "Aprendizaje / pasantía"

    class Status(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        EMITIDO = "EMITIDO", "Emitido"
        FINALIZADO = "FINALIZADO", "Finalizado"
        ANULADO = "ANULADO", "Anulado"

    class SalaryPeriod(models.TextChoices):
        MENSUAL = "MENSUAL", "Mensual"
        QUINCENAL = "QUINCENAL", "Quincenal"
        SEMANAL = "SEMANAL", "Semanal"
        DIARIO = "DIARIO", "Diario"
        POR_OBRA = "POR_OBRA", "Por obra / producción"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="contracts")
    contract_type = models.CharField(max_length=16, choices=ContractType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.BORRADOR)
    position = models.ForeignKey(
        JobPosition, null=True, blank=True, on_delete=models.PROTECT, related_name="contracts"
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    salary_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    salary_period = models.CharField(
        max_length=16, choices=SalaryPeriod.choices, default=SalaryPeriod.MENSUAL
    )
    body = models.TextField(blank=True, default="")
    issued_at = models.DateTimeField(null=True, blank=True)
    # Renovación encadenada: este contrato renueva/continúa al anterior.
    renews = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="renewals"
    )
    # Control de firmas (ambas partes). fully_signed_at se setea cuando ambas firmaron.
    signed_employer_at = models.DateTimeField(null=True, blank=True)
    signed_employee_at = models.DateTimeField(null=True, blank=True)
    fully_signed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hr_contracts_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    # Tipos que exigen fecha de fin (relación con término definido).
    END_DATE_REQUIRED = (
        ContractType.PLAZO_FIJO,
        ContractType.TEMPORADA,
        ContractType.PRUEBA,
        ContractType.APRENDIZAJE,
    )

    class Meta:
        app_label = "hr"
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["status", "end_date"]),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self):
        super().clean()
        if self.contract_type in self.END_DATE_REQUIRED and not self.end_date:
            raise ValidationError({"end_date": "Este tipo de contrato requiere fecha de fin."})
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "La fecha de fin no puede ser anterior al inicio."})


class EmployeeMemo(models.Model):
    """Memorandos y actas de relaciones laborales (llamados de atención, acuerdos, etc.).

    Es el registro disciplinario/administrativo del trabajador. No se borra: se ANULA.
    """

    class MemoType(models.TextChoices):
        MEMORANDO = "MEMORANDO", "Memorando"
        AMONESTACION_VERBAL = "AMONESTACION_VERBAL", "Amonestación verbal (constancia)"
        AMONESTACION_ESCRITA = "AMONESTACION_ESCRITA", "Amonestación escrita"
        FELICITACION = "FELICITACION", "Felicitación / reconocimiento"
        ACUERDO = "ACUERDO", "Acta de acuerdo"
        OTRO = "OTRO", "Otro"

    class Status(models.TextChoices):
        EMITIDO = "EMITIDO", "Emitido"
        ANULADO = "ANULADO", "Anulado"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="memos")
    memo_type = models.CharField(max_length=32, choices=MemoType.choices, default=MemoType.MEMORANDO)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.EMITIDO)
    subject = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    issued_date = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hr_memos_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "hr"
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["employee", "memo_type"]),
        ]
        ordering = ["-issued_date", "-id"]


class EmploymentAssignment(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="assignments")
    position = models.ForeignKey(JobPosition, on_delete=models.PROTECT, related_name="assignments")
    branch = models.ForeignKey(
        OrgUnit, null=True, blank=True, on_delete=models.PROTECT, related_name="employment_assignments"
    )
    is_active = models.BooleanField(default=True)
    started_at = models.DateTimeField(default=timezone.now, editable=False)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employment_assignments_created",
    )

    class Meta:
        app_label = "hr"
        indexes = [
            models.Index(fields=["employee", "is_active"]),
            models.Index(fields=["employee", "is_active", "started_at"]),
            models.Index(fields=["position", "is_active"]),
            models.Index(fields=["branch", "is_active"]),
        ]


# ---------------------------------------------------------------------------
# Contratos a fondo: firmas y versionado del texto
# ---------------------------------------------------------------------------


class ContractSignature(models.Model):
    """Firma de una de las partes sobre un contrato emitido.

    El contrato queda PLENAMENTE FIRMADO cuando existen ambas firmas
    (EMPLEADOR y TRABAJADOR); el servicio setea EmploymentContract.fully_signed_at.
    """

    class PartyRole(models.TextChoices):
        EMPLEADOR = "EMPLEADOR", "El empleador"
        TRABAJADOR = "TRABAJADOR", "El trabajador"

    class Method(models.TextChoices):
        FISICA = "FISICA", "Física (papel)"
        DIGITAL = "DIGITAL", "Digital"

    contract = models.ForeignKey(
        EmploymentContract, on_delete=models.CASCADE, related_name="signatures"
    )
    party_role = models.CharField(max_length=16, choices=PartyRole.choices)
    signer_name = models.CharField(max_length=200)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.FISICA)
    signed_at = models.DateTimeField(default=timezone.now)
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hr_contract_signatures",
    )

    class Meta:
        app_label = "hr"
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "party_role"], name="uq_contract_signature_party"
            ),
        ]
        ordering = ["contract_id", "party_role"]


class ContractVersion(models.Model):
    """Versión inmutable del texto del contrato.

    v1 se captura al EMITIR (congela el body). Las adendas crean versiones
    siguientes sobre un contrato ya emitido, conservando la historia.
    """

    contract = models.ForeignKey(
        EmploymentContract, on_delete=models.CASCADE, related_name="versions"
    )
    version_no = models.PositiveIntegerField()
    body = models.TextField()
    salary_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    salary_period = models.CharField(max_length=16, blank=True, default="")
    reason = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hr_contract_versions_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "hr"
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "version_no"], name="uq_contract_version_no"
            ),
        ]
        ordering = ["contract_id", "version_no"]


# ---------------------------------------------------------------------------
# Vacaciones: política, ledger acumulable y solicitudes (registro directo RRHH)
# ---------------------------------------------------------------------------


class VacationPolicy(models.Model):
    """Política de acumulación de vacaciones por empresa.

    Default legal Nicaragua (Art. 76 CT): 2.5 días/mes (30/año). El tope
    opcional limita el saldo acumulable.
    """

    company = models.OneToOneField(
        OrgUnit, on_delete=models.CASCADE, related_name="vacation_policy"
    )
    days_per_month = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("2.5"),
        help_text="Días de vacaciones que se acumulan por mes trabajado.",
    )
    max_accrual_days = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text="Tope opcional del saldo acumulable (NULL = sin tope).",
    )
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vacation_policies_updated",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hr"


class VacationLedgerEntry(models.Model):
    """Movimiento del saldo de vacaciones (días con signo). Saldo = Σ days.

    ACCRUAL (+) acumulación mensual · TAKEN (−) vacaciones tomadas ·
    ADJUSTMENT (±) correcciones / saldos iniciales / reversa de anulación.
    """

    class EntryType(models.TextChoices):
        ACCRUAL = "ACCRUAL", "Acumulación"
        TAKEN = "TAKEN", "Vacaciones tomadas"
        ADJUSTMENT = "ADJUSTMENT", "Ajuste"

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="vacation_entries"
    )
    entry_type = models.CharField(max_length=12, choices=EntryType.choices)
    days = models.DecimalField(max_digits=7, decimal_places=2)
    occurred_on = models.DateField()
    # Para acumulación: período acreditado (idempotencia).
    accrual_year = models.PositiveSmallIntegerField(null=True, blank=True)
    accrual_month = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=200, blank=True, default="")
    request = models.ForeignKey(
        "hr.VacationRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ledger_entries",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vacation_entries_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "hr"
        constraints = [
            # Una sola acumulación por (empleado, año, mes) → idempotencia.
            models.UniqueConstraint(
                fields=["employee", "accrual_year", "accrual_month"],
                condition=models.Q(entry_type="ACCRUAL"),
                name="uq_vacation_accrual_period",
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "occurred_on"]),
            models.Index(fields=["employee", "entry_type"]),
        ]
        ordering = ["-occurred_on", "-id"]


class VacationRequest(models.Model):
    """Vacaciones registradas por RRHH (registro directo, sin doble firma).

    Al crearse queda APROBADA y descuenta el saldo (TAKEN). Anular reversa el
    saldo (ADJUSTMENT) y marca ANULADA.
    """

    class Status(models.TextChoices):
        APROBADA = "APROBADA", "Aprobada"
        ANULADA = "ANULADA", "Anulada"

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="vacation_requests"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    calendar_days = models.PositiveSmallIntegerField(default=0)
    business_days = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.APROBADA)
    reason = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vacation_requests_created",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vacation_requests_cancelled",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        app_label = "hr"
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["employee", "start_date"]),
        ]
        ordering = ["-start_date", "-id"]

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "La fecha de fin no puede ser anterior al inicio."})


# ---------------------------------------------------------------------------
# Expediente documental: documentos adjuntos del trabajador
# ---------------------------------------------------------------------------


class EmployeeDocument(models.Model):
    """Documento del expediente (cédula, INSS, títulos, certificados…).

    Mismo patrón de almacenamiento que EmployeePhoto/ScannedDocument: base64 en
    la DB, así el expediente viaja completo en respaldos/sync. Acepta PDF/JPG/PNG
    (validado por bytes) con tope de tamaño.
    """

    class Category(models.TextChoices):
        CEDULA = "CEDULA", "Cédula de identidad"
        INSS = "INSS", "Carné / constancia INSS"
        TITULO = "TITULO", "Título / diploma"
        CERTIFICADO_MEDICO = "CERTIFICADO_MEDICO", "Certificado médico"
        CONTRATO_FIRMADO = "CONTRATO_FIRMADO", "Contrato firmado (escaneado)"
        CONSTANCIA = "CONSTANCIA", "Constancia / referencia"
        ANTECEDENTES = "ANTECEDENTES", "Antecedentes / récord de policía"
        LICENCIA = "LICENCIA", "Licencia (conducir u otra)"
        OTRO = "OTRO", "Otro"

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="documents"
    )
    category = models.CharField(max_length=24, choices=Category.choices, default=Category.OTRO)
    title = models.CharField(max_length=200)
    file_data = models.TextField()  # base64 del archivo
    content_type = models.CharField(max_length=64, default="application/pdf")
    byte_size = models.PositiveIntegerField(default=0)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    notes = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hr_documents_uploaded",
    )
    uploaded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "hr"
        indexes = [
            models.Index(fields=["employee", "category"]),
            models.Index(fields=["employee", "uploaded_at"]),
        ]
        ordering = ["-uploaded_at", "-id"]
