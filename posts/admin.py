from django.contrib import admin

from .models import Post, Comment, PollOption


class PollOptionInline(admin.TabularInline):
    model = PollOption
    extra = 0


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'post_type', 'community', 'author', 'is_pinned', 'like_count', 'comment_count', 'created_at')
    list_filter = ('post_type', 'community', 'is_pinned')
    search_fields = ('title', 'body')
    inlines = [PollOptionInline]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('post', 'author', 'parent', 'created_at')
