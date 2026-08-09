import hashlib

from django.db import migrations, models


def backfill_token_hashes(apps, schema_editor):
    BiometricDevice = apps.get_model("nomina", "BiometricDevice")
    for device in BiometricDevice.objects.all().only("pk", "api_token").iterator():
        raw_token = str(device.api_token or "")
        if not raw_token:
            raise RuntimeError(f"BiometricDevice {device.pk} no tiene token legacy para migrar.")
        BiometricDevice.objects.filter(pk=device.pk).update(
            api_token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        )


class Migration(migrations.Migration):
    dependencies = [("nomina", "0019_backfill_entry_worker_code")]

    operations = [
        # Expansión: el hash entra nullable/único para permitir el backfill online.
        migrations.AddField(
            model_name="biometricdevice",
            name="api_token_hash",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        # Compatibilidad: el proceso antiguo aún puede autenticar por el campo
        # legacy hasta desplegar la versión hash-aware y ejecutar 0021.
        migrations.RunPython(backfill_token_hashes, migrations.RunPython.noop),
    ]
