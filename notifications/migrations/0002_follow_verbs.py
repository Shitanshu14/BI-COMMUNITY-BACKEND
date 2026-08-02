from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='verb',
            field=models.CharField(choices=[
                ('post_liked', 'liked your post'),
                ('post_commented', 'commented on your post'),
                ('community_joined', 'joined your community'),
                ('verification_approved', 'your verification was approved'),
                ('verification_rejected', 'your verification was rejected'),
                ('new_follower', 'started following you'),
                ('follow_requested', 'requested to follow you'),
                ('follow_accepted', 'accepted your follow request'),
            ], max_length=30),
        ),
    ]
