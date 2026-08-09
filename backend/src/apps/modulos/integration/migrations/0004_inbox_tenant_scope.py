import django.db.models.deletion
from django.db import migrations, models


def backfill_inbox_scope(apps, schema_editor):
    InboxEvent = apps.get_model("integration", "InboxEvent")
    OutboxEvent = apps.get_model("integration", "OutboxEvent")
    OrgUnit = apps.get_model("iam", "OrgUnit")

    for row in InboxEvent.objects.filter(company_id__isnull=True).iterator():
        outbox = OutboxEvent.objects.filter(event_id=row.event_id).only("company_id", "branch_id").first()
        company_id = outbox.company_id if outbox else None
        branch_id = outbox.branch_id if outbox else None
        if company_id is None and isinstance(row.payload, dict):
            scope = row.payload.get("scope") or {}
            candidate_company = scope.get("company_id")
            candidate_branch = scope.get("branch_id")
            if candidate_company and OrgUnit.objects.filter(pk=candidate_company, unit_type="COMPANY").exists():
                company_id = candidate_company
            if (
                company_id
                and candidate_branch
                and OrgUnit.objects.filter(pk=candidate_branch, unit_type="BRANCH", parent_id=company_id).exists()
            ):
                branch_id = candidate_branch
        InboxEvent.objects.filter(pk=row.pk).update(company_id=company_id, branch_id=branch_id)


class Migration(migrations.Migration):
    dependencies = [
        ("iam", "0003_orgunit_parent_type_name_idx"),
        ("integration", "0003_rename_integratio_consume_6ab9e4_idx_integration_consume_253f49_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="inboxevent",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="inbox_events_company",
                to="iam.orgunit",
            ),
        ),
        migrations.AddField(
            model_name="inboxevent",
            name="branch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="inbox_events_branch",
                to="iam.orgunit",
            ),
        ),
        migrations.RunPython(backfill_inbox_scope, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="inboxevent",
            constraint=models.CheckConstraint(
                condition=models.Q(branch__isnull=True) | models.Q(company__isnull=False),
                name="ck_inbox_branch_requires_company",
            ),
        ),
        migrations.AddIndex(
            model_name="inboxevent",
            index=models.Index(
                fields=["company", "branch", "status", "received_at"],
                name="integration_inbox_scope_idx",
            ),
        ),
    ]
