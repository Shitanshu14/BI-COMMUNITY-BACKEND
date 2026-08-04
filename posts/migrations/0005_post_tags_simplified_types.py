from django.db import migrations, models


OLD_TYPE_TO_TAG = {
    'knowledge': 'Knowledge',
    'project': 'Project',
    'resource': 'Resource',
}


def collapse_post_types(apps, schema_editor):
    """Phase 2: KNOWLEDGE / PROJECT / RESOURCE become POST + a tag instead
    of their own post_type, so existing rows need to be migrated forward
    rather than silently reinterpreted."""
    Post = apps.get_model('posts', 'Post')
    for old_type, tag in OLD_TYPE_TO_TAG.items():
        for post in Post.objects.filter(post_type=old_type):
            existing = post.tags or []
            if tag not in existing:
                existing = existing + [tag]
            post.tags = existing
            post.post_type = 'post'
            post.save(update_fields=['post_type', 'tags'])


def uncollapse_post_types(apps, schema_editor):
    """Best-effort reverse: a POST tagged Knowledge/Project/Resource goes
    back to that legacy post_type (first matching tag wins)."""
    Post = apps.get_model('posts', 'Post')
    tag_to_old_type = {v: k for k, v in OLD_TYPE_TO_TAG.items()}
    for post in Post.objects.filter(post_type='post'):
        for tag in post.tags or []:
            if tag in tag_to_old_type:
                post.post_type = tag_to_old_type[tag]
                post.save(update_fields=['post_type'])
                break


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0004_comment_parent_post_pinned'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='tags',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(collapse_post_types, uncollapse_post_types),
        migrations.AlterField(
            model_name='post',
            name='post_type',
            field=models.CharField(
                choices=[('question', 'Question'), ('post', 'Post'), ('poll', 'Poll')],
                default='question', max_length=20,
            ),
        ),
    ]
