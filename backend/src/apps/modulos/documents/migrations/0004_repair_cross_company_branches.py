from django.db import migrations


def repair_cross_company_branches(apps, schema_editor):
    ScannedDocument = apps.get_model("documents", "ScannedDocument")
    invalid_ids = []
    for row in ScannedDocument.objects.exclude(branch_id__isnull=True).select_related("branch").iterator():
        if row.branch.parent_id != row.company_id:
            invalid_ids.append(row.pk)
    if invalid_ids:
        ScannedDocument.objects.filter(pk__in=invalid_ids).update(branch_id=None)


class Migration(migrations.Migration):
    dependencies = [("documents", "0003_alter_scanneddocument_doc_type")]

    operations = [migrations.RunPython(repair_cross_company_branches, migrations.RunPython.noop)]
