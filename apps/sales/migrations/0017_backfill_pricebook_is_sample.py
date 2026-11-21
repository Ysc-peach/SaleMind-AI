"""Mark the placeholder rows that predate the flag.

The eight rows written by seed_price_book before this field existed carry
is_sample=False, which is the unsafe direction: the export gate would let them
through. Prefix matching is acceptable exactly once, here, as a backfill.
"""

from django.db import migrations


def mark_placeholders(apps, schema_editor):
    PriceBookEntry = apps.get_model("sales", "PriceBookEntry")
    PriceBookEntry.objects.filter(sku__startswith="DEMO-").update(is_sample=True)


def unmark_placeholders(apps, schema_editor):
    PriceBookEntry = apps.get_model("sales", "PriceBookEntry")
    PriceBookEntry.objects.filter(sku__startswith="DEMO-").update(is_sample=False)


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0016_pricebookentry_is_sample"),
    ]

    operations = [
        migrations.RunPython(mark_placeholders, unmark_placeholders),
    ]
