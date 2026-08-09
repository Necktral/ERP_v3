from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("facturacion", "0011_billingpayment_idempotency_key_and_more")]

    operations = [
        migrations.AlterField(
            model_name="billingpayment",
            name="idempotency_key",
            field=models.CharField(blank=True, default="", max_length=96),
        ),
        migrations.RemoveConstraint(
            model_name="billingpayment",
            name="uq_billpay_doc_idem",
        ),
        migrations.AddConstraint(
            model_name="billingpayment",
            constraint=models.UniqueConstraint(
                condition=~models.Q(idempotency_key=""),
                fields=("company", "idempotency_key"),
                name="uq_billpay_company_idem",
            ),
        ),
    ]
