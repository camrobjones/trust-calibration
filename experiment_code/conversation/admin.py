from django.contrib import admin

from conversation.models import AIPersuader, Question


class AIPersuaderAdmin(admin.ModelAdmin):
    list_display = ("name", "model_name", "active")
    list_filter = ("active",)
    search_fields = ("name", "model_name")
    ordering = ("name",)
    actions = ["activate", "deactivate"]

    def activate(self, request, queryset):
        queryset.update(active=True)

    def deactivate(self, request, queryset):
        queryset.update(active=False)


admin.site.register(AIPersuader, AIPersuaderAdmin)

# Question


class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "category",
        "question",
        "answer1",
        "answer2",
        "correct_answer",
    )
    list_filter = ("category",)
    search_fields = ("question",)
    ordering = ("id",)


admin.site.register(Question, QuestionAdmin)
