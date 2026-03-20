from __future__ import annotations

from garth import http
from garth.data.activity import Activity as _Activity


class Activity(_Activity):
    """Extended Activity with date-range query support."""

    @classmethod
    def list_by_date(
        cls,
        start_date: str,
        end_date: str,
        *,
        client: http.Client | None = None,
    ) -> list[dict]:
        """Fetch all activities between start_date and end_date.

        Paginates through all results (20 per page) to collect every
        activity in the range, matching the behaviour of
        garminconnect's ``get_activities_by_date()``.

        Args:
            start_date: Start date in ``YYYY-MM-DD`` format.
            end_date: End date in ``YYYY-MM-DD`` format.
            client: Optional HTTP client (uses the global default if
                not provided).

        Returns:
            A list of raw activity dicts as returned by the Garmin
            Connect API.
        """
        client = client or http.client
        path = "/activitylist-service/activities/search/activities"
        all_activities: list[dict] = []
        start = 0
        limit = 20

        while True:
            params = {
                "startDate": start_date,
                "endDate": end_date,
                "start": str(start),
                "limit": str(limit),
            }
            data = client.connectapi(path, params=params)
            if not data:
                break
            assert isinstance(data, list)
            all_activities.extend(data)
            start += limit

        return all_activities
