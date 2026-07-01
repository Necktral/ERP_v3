from django.urls import path

from .views import (
    KnowledgeAssistantView,
    KnowledgeChatView,
    KnowledgeDevChatView,
    KnowledgeDevExportView,
    KnowledgeDevFeedbackView,
    KnowledgeSearchView,
    KnowledgeSuggestionsView,
    KnowledgeSummaryView,
)

urlpatterns = [
    path("search/", KnowledgeSearchView.as_view(), name="knowledge-search"),
    path("assistant/", KnowledgeAssistantView.as_view(), name="knowledge-assistant"),
    path("chat/", KnowledgeChatView.as_view(), name="knowledge-chat"),
    path("summary/", KnowledgeSummaryView.as_view(), name="knowledge-summary"),
    path("suggestions/", KnowledgeSuggestionsView.as_view(), name="knowledge-suggestions"),
    path("dev/feedback/", KnowledgeDevFeedbackView.as_view(), name="knowledge-dev-feedback"),
    path("dev/chat/", KnowledgeDevChatView.as_view(), name="knowledge-dev-chat"),
    path("dev/feedback-export/", KnowledgeDevExportView.as_view(), name="knowledge-dev-export"),
]
