# Identidad de sync (F0): agrega sync_uid (ULID) + origin_node a PayrollPayment.
#
# Migración data-safe para filas existentes: el sync_uid se agrega primero como
# NULL (sin unique), se rellena por fila con un ULID único y se registra en el mapa
# de identidad, y recién entonces se vuelve único + NOT NULL. Así no rompe en una DB
# de un nodo que ya tenga pagos (no se puede agregar una columna única con un solo
# default a filas existentes).
import apps.modulos.common.sync_identity as sync_identity
from django.db import migrations, models


def fill_sync_uid(apps, schema_editor):
    """Rellena sync_uid por fila con un ULID único y registra la identidad local."""
    PayrollPayment = apps.get_model("nomina", "PayrollPayment")
    SyncIdentity = apps.get_model("common", "SyncIdentity")
    node = sync_identity.current_node_code()
    label = "nomina.payrollpayment"
    pending = PayrollPayment.objects.filter(sync_uid__isnull=True).values_list("pk", flat=True)
    for pk in list(pending):
        uid = sync_identity.new_ulid()
        PayrollPayment.objects.filter(pk=pk).update(sync_uid=uid)
        SyncIdentity.objects.get_or_create(
            model_label=label,
            sync_uid=uid,
            defaults={"local_id": pk, "origin_node": node},
        )


def noop_reverse(apps, schema_editor):
    # Al revertir se elimina la columna; el mapa de identidad puede quedar (idempotente).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('nomina', '0014_salarycomplementsheet_salarycomplementline_and_more'),
        ('common', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='payrollpayment',
            name='origin_node',
            field=models.CharField(default=sync_identity.current_node_code, editable=False, help_text='Código del nodo que creó la fila.', max_length=40),
        ),
        # 1) columna temporal NULL (sin unique) para no chocar en filas existentes
        migrations.AddField(
            model_name='payrollpayment',
            name='sync_uid',
            field=models.CharField(editable=False, help_text='Identidad global de la fila entre nodos (ULID).', max_length=26, null=True),
        ),
        # 2) rellenar con ULIDs únicos + registrar en el mapa de identidad
        migrations.RunPython(fill_sync_uid, noop_reverse),
        # 3) ahora sí: único + NOT NULL + default para filas nuevas
        migrations.AlterField(
            model_name='payrollpayment',
            name='sync_uid',
            field=models.CharField(default=sync_identity.new_ulid, editable=False, help_text='Identidad global de la fila entre nodos (ULID).', max_length=26, unique=True),
        ),
    ]
