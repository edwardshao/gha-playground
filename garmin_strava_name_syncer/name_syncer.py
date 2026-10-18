#!/usr/bin/env python3

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
import requests

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from garth.exc import GarthHTTPError

GARMIN_TOKENS_BASE64 = os.getenv("GARMIN_TOKENS_BASE64")
GARMIN_ACTIVITIES_OUTPUT_PATH = "garmin_activities.json"

STRAVA_COOKIE = os.getenv("STRAVA_COOKIE")
STRAVA_ACTIVITIES_OUTPUT_PATH = "strava_activities.json"
STRAVA_UPDATED_COOKIE_PATH = ".strava_updated_cookie"


class StravaWebClient:
    """Lightweight client using Strava's internal Web API (supports automatic cookie renewal)."""

    BASE_URL = "https://www.strava.com"

    def __init__(self, cookie_str: str):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0.0.0 Safari/537.36"
                ),
            }
        )
        # Parse the cookie string into the session CookieJar so requests can handle Set-Cookie updates automatically
        self._load_cookie_str(cookie_str)
        self.csrf_token = self._fetch_csrf_token()

    def _load_cookie_str(self, cookie_str: str) -> None:
        """Load a 'k1=v1; k2=v2' formatted cookie string into the requests CookieJar."""
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                self.session.cookies.set(k.strip(), v.strip(), domain=".strava.com")

    def export_cookie_str(self) -> str:
        """Export the latest cookies from the current session as a formatted string."""
        cookie_dict = {}
        for c in self.session.cookies:
            cookie_dict[c.name] = c.value
        return "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])

    def save_updated_cookie(self, filepath: str = STRAVA_UPDATED_COOKIE_PATH) -> None:
        """Save the refreshed cookies to a local file for GitHub Actions to update the repository secret."""
        updated_cookie = self.export_cookie_str()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(updated_cookie)
        print(f"🔄 Updated Strava cookies saved to {filepath}")

    def _fetch_csrf_token(self) -> str:
        """Fetch the CSRF token from the training log page and verify authentication status."""
        resp = self.session.get(
            f"{self.BASE_URL}/athlete/training", allow_redirects=False
        )
        if resp.status_code in (301, 302):
            raise RuntimeError(
                "Strava cookie is expired or invalid (redirected to login page). Please update STRAVA_COOKIE."
            )
        resp.raise_for_status()

        match = re.search(
            r'<meta\s+name="csrf-token"\s+content="([^"]+)"', resp.text
        )
        if not match:
            raise RuntimeError("Failed to parse csrf-token from Strava page.")

        return match.group(1)

    def get_recent_activities(self, page: int = 1) -> list:
        """Fetch recent activities via the internal training log API (20 activities per page)."""
        url = f"{self.BASE_URL}/athlete/training_activities"
        params = {
            "keywords": "",
            "activity_type": "",
            "workout_type": "",
            "commute": "",
            "private_activities": "",
            "trainer": "",
            "gear": "",
            "new_activity_only": "false",
            "page": page,
            "per_page": 20,
        }
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": self.csrf_token,
            "Referer": f"{self.BASE_URL}/athlete/training",
        }
        resp = self.session.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("models", [])

    def update_activity_name(self, activity_id: int, new_name: str) -> None:
        """Update activity name via the internal Web API."""
        url = f"{self.BASE_URL}/athlete/training_activities/{activity_id}"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": self.csrf_token,
            "Referer": f"{self.BASE_URL}/athlete/training",
        }
        payload = {"name": new_name}
        resp = self.session.put(url, json=payload, headers=headers)

        # Fallback to standard activity form submission if inline edit returns an unexpected status code
        if resp.status_code not in (200, 204):
            fallback_url = f"{self.BASE_URL}/activities/{activity_id}"
            form_data = {
                "_method": "patch",
                "authenticity_token": self.csrf_token,
                "activity[name]": new_name,
            }
            resp2 = self.session.post(
                fallback_url,
                data=form_data,
                headers={"Referer": f"{self.BASE_URL}/activities/{activity_id}/edit"},
            )
            resp2.raise_for_status()
        else:
            resp.raise_for_status()


def init_garmin_api():
    """Initialize Garmin API with your credentials."""
    try:
        # Using Oauth1 and Oauth2 tokens from base64 encoded string
        print(
            "ℹ️ Trying to login to Garmin Connect using token data from GARMIN_TOKENS_BASE64 env..."
        )

        garmin = Garmin()
        garmin.login(GARMIN_TOKENS_BASE64)

    except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError) as err:
        print(f"❌ Initialize Garmin API error: {err}")
        return None

    return garmin


def init_strava_client():
    """Initialize Strava Web Client with Cookie."""
    try:
        print(
            "ℹ️ Trying to connect to Strava Web using cookie from STRAVA_COOKIE env..."
        )
        client = StravaWebClient(STRAVA_COOKIE)
        print("✅ Connected to Strava Web successfully!")
        return client
    except Exception as err:
        print(f"❌ Initialize Strava Web Client error: {err}")
        return None


def garmin_safe_api_call(api_method, *args, **kwargs):
    """
    Safe API call wrapper with comprehensive error handling.

    This demonstrates the error handling patterns used throughout the library.
    Returns (success: bool, result: Any, error_message: str)
    """
    try:
        result = api_method(*args, **kwargs)
        return True, result, None

    except GarthHTTPError as e:
        # Handle specific HTTP errors gracefully
        error_str = str(e)
        status_code = getattr(getattr(e, "response", None), "status_code", None)

        if status_code == 400 or "400" in error_str:
            return (
                False,
                None,
                "Endpoint not available (400 Bad Request) - Feature may not be enabled for your account",
            )
        elif status_code == 401 or "401" in error_str:
            return (
                False,
                None,
                "Authentication required (401 Unauthorized) - Please re-authenticate",
            )
        elif status_code == 403 or "403" in error_str:
            return (
                False,
                None,
                "Access denied (403 Forbidden) - Account may not have permission",
            )
        elif status_code == 404 or "404" in error_str:
            return (
                False,
                None,
                "Endpoint not found (404) - Feature may have been moved or removed",
            )
        elif status_code == 429 or "429" in error_str:
            return (
                False,
                None,
                "Rate limit exceeded (429) - Please wait before making more requests",
            )
        elif status_code == 500 or "500" in error_str:
            return (
                False,
                None,
                "Server error (500) - Garmin's servers are experiencing issues",
            )
        elif status_code == 503 or "503" in error_str:
            return (
                False,
                None,
                "Service unavailable (503) - Garmin's servers are temporarily unavailable",
            )
        else:
            return False, None, f"HTTP error: {e}"

    except FileNotFoundError:
        return (
            False,
            None,
            "No valid tokens found. Please login with your email/password to create new tokens.",
        )

    except GarminConnectAuthenticationError as e:
        return False, None, f"Authentication issue: {e}"

    except GarminConnectConnectionError as e:
        return False, None, f"Connection issue: {e}"

    except GarminConnectTooManyRequestsError as e:
        return False, None, f"Rate limit exceeded: {e}"

    except Exception as e:
        return False, None, f"Unexpected error: {e}"


def _sort_and_save_activities(activity_map, output_path):
    """Sorts activities by timestamp and saves them to a JSON file."""
    # sort hashmap by keys
    sorted_items = sorted(
        activity_map.items(),
        key=lambda item: datetime.strptime(item[0], "%Y-%m-%d %H:%M:%S"),
    )
    sorted_data = dict(sorted_items)

    # Save hashmap to file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sorted_data, f, ensure_ascii=False, indent=4)

    print(f"\nActivities saved to {output_path}")

    return sorted_data


def get_garmin_activities(garmin_api, after_datetime_utc, before_datetime_utc):
    # convert datetime to UTC+8
    after_datetime_utc8 = after_datetime_utc.astimezone(timezone(timedelta(hours=8)))
    before_datetime_utc8 = before_datetime_utc.astimezone(timezone(timedelta(hours=8)))

    after_date = after_datetime_utc8.strftime("%Y-%m-%d")
    before_date = before_datetime_utc8.strftime("%Y-%m-%d")

    print(f"=== Getting Garmin activities from {after_date} to {before_date} (UTC+8)")

    # Initialize hashmap
    activity_map = {}

    success, activities, error_msg = garmin_safe_api_call(
        garmin_api.get_activities_by_date, after_date, before_date
    )

    if not success:
        print(f"❌ Failed to get activities from {after_date} to {before_date}.")
        print(f"   Error: {error_msg}")
    elif not activities:
        print(f"ℹ️ Can not find activities from {after_date} to {before_date}.")
    else:
        print(f"✅ Retrieved {len(activities)} activities from Garmin Connect.")

        for activity in activities:
            activity_id = activity.get("activityId")
            activity_name = activity.get("activityName")
            activity_start_time_gmt = activity.get("startTimeGMT")

            # Add to hashmap with formatted_start_date as key
            activity_map[activity_start_time_gmt] = {
                "id": activity_id,
                "name": activity_name,
            }

            print("Activity:")
            print(f"\tid: {activity_id}")
            print(f"\tname: {activity_name}")
            print(f"\tstart_date: {activity_start_time_gmt}")

    sorted_data = _sort_and_save_activities(activity_map, GARMIN_ACTIVITIES_OUTPUT_PATH)

    return success, sorted_data


def get_strava_activities(
    strava_client: StravaWebClient, after_datetime_utc, before_datetime_utc
):
    # convert datetime to UTC+8
    after_datetime_utc8 = after_datetime_utc.astimezone(timezone(timedelta(hours=8)))
    before_datetime_utc8 = before_datetime_utc.astimezone(timezone(timedelta(hours=8)))

    print(
        f"=== Getting Strava activities from {after_datetime_utc8.date()} to {before_datetime_utc8.date()} (UTC+8)"
    )

    # Initialize hashmap
    activity_map = {}

    # Set time boundaries for the date range in UTC+8
    after_bound = after_datetime_utc8.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    before_bound = before_datetime_utc8.replace(
        hour=23, minute=59, second=59, microsecond=999999
    )

    success = True
    try:
        # Fetch the first 2 pages (up to 40 activities) to cover the last 7 days
        models = []
        for page in (1, 2):
            page_models = strava_client.get_recent_activities(page=page)
            if not page_models:
                break
            models.extend(page_models)

        for item in models:
            # Example start_time format from Strava Web API: "2026-10-15T22:30:15+0000" (UTC)
            start_time_str = item.get("start_time")
            if not start_time_str:
                continue

            act_dt_utc = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S%z")

            if after_bound <= act_dt_utc <= before_bound:
                # Format as naive UTC string "%Y-%m-%d %H:%M:%S" to match Garmin's startTimeGMT
                formatted_start_date = act_dt_utc.astimezone(timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                act_id = item.get("id")
                act_name = item.get("name")

                # Add to hashmap with formatted_start_date as key
                activity_map[formatted_start_date] = {
                    "id": act_id,
                    "name": act_name,
                }

                print("Activity:")
                print(f"\tid: {act_id}")
                print(f"\tname: {act_name}")
                print(f"\tstart_date: {formatted_start_date}")

        if not activity_map:
            print(
                f"ℹ️ Can not find activities from {after_datetime_utc8.date()} to {before_datetime_utc8.date()}."
            )
        else:
            print(f"✅ Retrieved {len(activity_map)} activities from Strava.")

    except Exception as e:
        print(
            f"❌ Failed to get activities from {after_datetime_utc8.date()} to {before_datetime_utc8.date()}. - {e}"
        )
        success = False

    sorted_data = _sort_and_save_activities(activity_map, STRAVA_ACTIVITIES_OUTPUT_PATH)

    return success, sorted_data


def strava_update_activity_name(strava_client: StravaWebClient, activity_id, new_name):
    print(f'Updating Strava activity ID {activity_id} name to "{new_name}"...')

    try:
        strava_client.update_activity_name(activity_id, new_name)
        print(f'✅ Update Strava activity name to "{new_name}" successfully')
    except Exception as e:
        print(f"❌ Fail to update activity name - {e}")


def sync_name_from_garmin_to_strava(
    garmin_activities, strava_activities, strava_client, sync_ignore_list
):
    print("=== Syncing activity names from Garmin to Strava...")

    print(f"Sync ignore list: {sync_ignore_list}")

    for garmin_timestamp, garmin_activity in garmin_activities.items():
        garmin_activity_name = garmin_activity.get("name", "N/A")

        if sync_ignore_list and garmin_activity_name.startswith(
            tuple(sync_ignore_list)
        ):
            print(
                f'ℹ️ Skipping the Garmin activity ({garmin_timestamp}) as its name "{garmin_activity_name}" is in the ignore list.'
            )
            continue

        if garmin_timestamp in strava_activities:
            strava_activity_name = strava_activities[garmin_timestamp].get(
                "name", "N/A"
            )
            if garmin_activity_name != strava_activity_name:
                print(
                    f'Timestamp: {garmin_timestamp}, Garmin Name: "{garmin_activity_name}", Strava Name: "{strava_activity_name}" (Names differ)'
                )

                strava_id = strava_activities[garmin_timestamp].get("id")
                print(
                    f'ℹ️ Update Garmin Name: "{garmin_activity_name}" to Strava activity ({strava_id})'
                )
                strava_update_activity_name(
                    strava_client, strava_id, garmin_activity_name
                )


def env_pre_check():
    if not GARMIN_TOKENS_BASE64:
        print("GARMIN_TOKENS_BASE64 environment variable is not set.")
        exit(1)
    if not STRAVA_COOKIE:
        print("STRAVA_COOKIE environment variable is not set.")
        exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync Garmin activity names to Strava."
    )
    parser.add_argument(
        "--sync-ignore-file",
        type=str,
        help="Path to a file containing a list of activity name prefixes to ignore during sync.",
        default=None,
    )
    args = parser.parse_args()

    sync_ignore_list = []
    if args.sync_ignore_file:
        try:
            with open(args.sync_ignore_file, "r", encoding="utf-8") as f:
                sync_ignore_list = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            print(f"❌ Sync ignore file not found: {args.sync_ignore_file}")
            exit(1)

    try:
        env_pre_check()

        # Initialize Garmin API
        garmin_api = init_garmin_api()
        if not garmin_api:
            print("Fail to init Garmin API")
            exit(1)

        # Initialize Strava Web Client
        strava_client = init_strava_client()
        if not strava_client:
            print("Fail to init Strava client")
            exit(1)

        # Export refreshed Strava session cookies immediately after successful authentication
        strava_client.save_updated_cookie(STRAVA_UPDATED_COOKIE_PATH)

        # Define date range for activities (last 7 days)
        before_datetime_utc = datetime.now(timezone.utc)
        after_datetime_utc = before_datetime_utc - timedelta(days=7)

        # Get Garmin activities
        success, garmin_activities = get_garmin_activities(
            garmin_api, after_datetime_utc, before_datetime_utc
        )

        if success and garmin_activities:
            print(f"Found {len(garmin_activities)} activities from Garmin")

            # Get Strava activities
            success, strava_activities = get_strava_activities(
                strava_client, after_datetime_utc, before_datetime_utc
            )

            if success and strava_activities:
                print(f"Found {len(strava_activities)} activities from Strava")
                # Sync activity names from Garmin to Strava
                sync_name_from_garmin_to_strava(
                    garmin_activities,
                    strava_activities,
                    strava_client,
                    sync_ignore_list,
                )
            else:
                if not success:
                    print("❌ Failed to get Strava activities.")
                else:
                    print("ℹ️ No Strava activities found to sync.")

            # Save cookies again in case subsequent requests issued new session cookies
            strava_client.save_updated_cookie(STRAVA_UPDATED_COOKIE_PATH)
        else:
            if not success:
                print("❌ Failed to get Garmin activities.")
            else:
                print("ℹ️ No Garmin activities found to sync.")
    except Exception as e:
        print(f"Error when syncing activity name: {e}")
        exit(1)