from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_user_email_confirmed'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_private',
            field=models.BooleanField(default=False),
        ),
    ]
