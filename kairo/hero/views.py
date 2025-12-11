"""
Views for the hero app.

PR-0: Only healthcheck endpoint.
"""

from django.http import JsonResponse


def healthcheck(request):
    """
    Simple healthcheck endpoint.

    Returns 200 OK with status info.
    Used to verify the Django app is running correctly.
    """
    return JsonResponse({
        "status": "ok",
        "service": "kairo-backend",
    })


# PRD-1: out of scope for PR-0 - future views:
#
# def today_board(request, brand_id):
#     """GET /api/brands/{brand_id}/today - returns TodayBoardDTO"""
#     pass
#
# def regenerate_today(request, brand_id):
#     """POST /api/brands/{brand_id}/today/regenerate - triggers F1 flow"""
#     pass
#
# def create_package(request, brand_id, opp_id):
#     """POST /api/brands/{brand_id}/opportunities/{opp_id}/packages - triggers F2 flow"""
#     pass
