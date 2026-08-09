import django.db.models.deletion
from django.db import migrations, models


def backfill_error_scope(apps, schema_editor):
    ErrorEvent = apps.get_model("diagnostics", "ErrorEvent")
    OrgUnit = apps.get_model("iam", "OrgUnit")

    for row in ErrorEvent.objects.filter(company_id__isnull=True).iterator():
        raw_company = str(row.company_legacy_id or "").strip()
        raw_branch = str(row.branch_legacy_id or "").strip()
        company = None
        branch = None
        if raw_company.isdigit():
            company = OrgUnit.objects.filter(pk=int(raw_company), unit_type="COMPANY").first()
        if company is not None and raw_branch.isdigit():
            branch = OrgUnit.objects.filter(
                pk=int(raw_branch), unit_type="BRANCH", parent_id=company.pk
            ).first()
        ErrorEvent.objects.filter(pk=row.pk).update(
            company_id=getattr(company, "pk", None),
            branch_id=getattr(branch, "pk", None),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("iam", "0003_orgunit_parent_type_name_idx"),
        ("diagnostics", "0005_codeunitevidence"),
    ]

    operations = [
        migrations.RenameField(
            model_name="errorevent", old_name="company_id", new_name="company_legacy_id"
        ),
        migrations.RenameField(
            model_name="errorevent", old_name="branch_id", new_name="branch_legacy_id"
        ),
        migrations.AddField(
            model_name="errorevent",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="diagnostic_errors_company",
                to="iam.orgunit",
            ),
        ),
        migrations.AddField(
            model_name="errorevent",
            name="branch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="diagnostic_errors_branch",
                to="iam.orgunit",
            ),
        ),
        migrations.RunPython(backfill_error_scope, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="errorevent", name="stack_hash", field=models.CharField(max_length=64)
        ),
        migrations.AddConstraint(
            model_name="errorevent",
            constraint=models.UniqueConstraint(
                fields=("stack_hash", "company"), name="uq_error_stack_company"
            ),
        ),
        migrations.AddConstraint(
            model_name="errorevent",
            constraint=models.UniqueConstraint(
                fields=("stack_hash",),
                condition=models.Q(company__isnull=True),
                name="uq_error_stack_global",
            ),
        ),
        migrations.AddConstraint(
            model_name="errorevent",
            constraint=models.CheckConstraint(
                condition=models.Q(branch__isnull=True) | models.Q(company__isnull=False),
                name="ck_error_branch_requires_company",
            ),
        ),
        migrations.AddIndex(
            model_name="errorevent",
            index=models.Index(
                fields=["company", "status", "-last_seen_at"],
                name="diagnostics_error_scope_idx",
            ),
        ),
    ]
