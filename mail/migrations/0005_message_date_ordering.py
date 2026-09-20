from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("mail", "0004_message_send_time")]

    operations = [
        migrations.AlterModelOptions(
            name="message",
            options={"ordering": ["send_date", "created_at", "pk"]},
        ),
    ]
