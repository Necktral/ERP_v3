from django.urls import path

from .views import (
    CompanyListCreateView,
    CompanyModulesView,
    CompanyProfileView,
    BranchDetailView,
    BranchListCreateView,
    IntercompanyRelationshipDetailView,
    IntercompanyRelationshipListCreateView,
    OrgBrandingView,
)

urlpatterns = [
    path("branding/", OrgBrandingView.as_view(), name="org-branding"),
    path("company/profile/", CompanyProfileView.as_view(), name="org-company-profile"),
    path("companies/", CompanyListCreateView.as_view(), name="org-companies"),
    path("branches/", BranchListCreateView.as_view(), name="org-branches"),
    path("branches/<int:branch_id>/", BranchDetailView.as_view(), name="org-branch-detail"),
    path("modules/", CompanyModulesView.as_view(), name="org-modules"),
    path("intercompany-relationships/", IntercompanyRelationshipListCreateView.as_view(), name="org-intercompany-relationships"),
    path("intercompany-relationships/<int:rel_id>/", IntercompanyRelationshipDetailView.as_view(), name="org-intercompany-relationship-detail"),
]
