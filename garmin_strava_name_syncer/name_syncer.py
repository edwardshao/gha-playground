#!/usr/bin/env python3

import base64
import os
import json
from garminconnect import Garmin
from datetime import datetime, timezone, timedelta
from getpass import getpass

from stravalib import Client

import requests
from garth.exc import GarthHTTPError
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

GARMIN_TOKENS_BASE64 = os.getenv("GARMIN_TOKENS_BASE64")
GARMIN_ACTIVITIES_OUTPUT_PATH="garmin_activities.json"

STRAVA_TOKEN_PATH="strava_token.json"
STRAVA_ACTIVITIES_OUTPUT_PATH="strava_activities.json"

SYNC_IGNORE="syncginore.txt"

def init_garmin_api():
    """Initialize Garmin API with your credentials."""
    try:
        # Using Oauth1 and Oauth2 tokens from base64 encoded string
        print("ℹ️ Trying to login to Garmin Connect using token data from GARMIN_TOKENS_BASE64 env...")

        garmin = Garmin()
        garmin.login(GARMIN_TOKENS_BASE64)

    except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError) as err:
        print(f"❌ Initialize Garmin API error: {err}")
        return None

    return garmin


def init_strava_client():
    with open(STRAVA_TOKEN_PATH, "r") as f:
        token_refresh = json.load(f)

    print("Strava token expires at", token_refresh["expires_at"])

    client = Client(
        access_token=token_refresh["access_token"],
        refresh_token=token_refresh["refresh_token"],
        token_expires=token_refresh["expires_at"],
    )

    return client


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


def get_garmin_activities(garmin_api, after_datetime_utc, before_datetime_utc):
    # convert datetime to UTC+8
    after_datetime_utc8 = after_datetime_utc.astimezone(timezone(timedelta(hours=8)))
    before_datetime_utc8 = before_datetime_utc.astimezone(timezone(timedelta(hours=8)))
    
    after_date = after_datetime_utc8.strftime('%Y-%m-%d')
    before_date = before_datetime_utc8.strftime('%Y-%m-%d')

    print(f"=== Getting Garmin activities from {after_date} to {before_date} (UTC+8)")

    # Initialize hashmap
    activity_map = {}

    success, activities, error_msg = garmin_safe_api_call(
        garmin_api.get_activities_by_date,
        after_date,
        before_date
    )

    if not success:
        print(f"❌ Failed to get activities from {after_date} to {before_date}.")
        print(f"   Error: {error_msg}")
    else:
        print(f"✅ Retrieved {len(activities)} activities from Garmin Connect.")

        for activity in activities:
            activity_id = activity.get("activityId")
            activity_name = activity.get("activityName")
            activity_start_time_gmt = activity.get("startTimeGMT")

            # Add to hashmap with formatted_start_date as key
            activity_map[activity_start_time_gmt] = {
                "id": activity_id,
                "name": activity_name
            }

            print(f"Activity:")
            print(f"\tid: {activity_id}")
            print(f"\tname: {activity_name}")
            print(f"\tstart_date: {activity_start_time_gmt}")

    # sort hashmap by keys
    sorted_items = sorted(activity_map.items(), key=lambda item: datetime.strptime(item[0], '%Y-%m-%d %H:%M:%S'))
    sorted_data = dict(sorted_items)

    # Save hashmap to file
    with open(GARMIN_ACTIVITIES_OUTPUT_PATH, "w", encoding='utf-8') as f:
        json.dump(sorted_data, f, ensure_ascii=False, indent=4)

    print(f"\nActivities saved to {GARMIN_ACTIVITIES_OUTPUT_PATH}")

    return success, sorted_data


def get_strava_activities(strava_client, after_datetime_utc, before_datetime_utc):
    # convert datetime to UTC+8
    after_datetime_utc8 = after_datetime_utc.astimezone(timezone(timedelta(hours=8)))
    before_datetime_utc8 = before_datetime_utc.astimezone(timezone(timedelta(hours=8)))

    print(f"=== Getting Strava activities from {after_datetime_utc8.date()} to {before_datetime_utc8.date()} (UTC+8)")

    # Initialize hashmap
    activity_map = {}

    # Remove time part for after and before datetime
    after_datetime_utc8_no_time = after_datetime_utc8.replace(hour=0, minute=0, second=0, microsecond=0)
    before_datetime_utc8_no_time = before_datetime_utc8.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        # Get activities in the date range
        activities = strava_client.get_activities(after=after_datetime_utc8_no_time, before=before_datetime_utc8_no_time)
        print(f"✅ Retrieved {len(list(activities))} activities from Strava.")
    except Exception as e:
        print(f"❌ Failed to get activities from {after_datetime_utc8.date()} to {before_datetime_utc8.date()}. - {e}")
        return False, {}

    for i, activity in enumerate(activities):
        # Format start_date
        formatted_start_date = activity.start_date.strftime('%Y-%m-%d %H:%M:%S')

        # Add to hashmap with formatted_start_date as key
        activity_map[formatted_start_date] = {
            "id": activity.id,
            "name": activity.name
        }

        print(f"Activity:")
        print(f"\tid: {activity.id}")
        print(f"\tname: {activity.name}")
        print(f"\tstart_date: {formatted_start_date}")

    # sort hashmap by keys
    sorted_items = sorted(activity_map.items(), key=lambda item: datetime.strptime(item[0], '%Y-%m-%d %H:%M:%S'))
    sorted_data = dict(sorted_items)

    # Save hashmap to file
    with open(STRAVA_ACTIVITIES_OUTPUT_PATH, "w", encoding='utf-8') as f:
        json.dump(sorted_data, f, ensure_ascii=False, indent=4)

    print(f"\nActivities saved to {STRAVA_ACTIVITIES_OUTPUT_PATH}")

    return True, sorted_data


def strava_update_activity_name(strava_client, activity_id, new_name):
    print(f"Updating Strava activity ID {activity_id} name to \"{new_name}\"...")

    try:
        strava_client.update_activity(activity_id, name=new_name)
        print(f"✅ Update Strava activity name to \"{new_name}\" successfully")
    except Exception as e:
        print(f"❌ Fail to update activity name - {e}")


def sync_name_from_garmin_to_strava(garmin_activities, strava_activities, strava_client):
    print("=== Syncing activity names from Garmin to Strava...")

    # read sync ignore list
    sync_ignore_list = []
    with open(SYNC_IGNORE, "r", encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                sync_ignore_list.append(line)
    print(f"Sync ignore list: {sync_ignore_list}")

    for garmin_timestamp, garmin_activity in garmin_activities.items():
        garmin_activity_name = garmin_activity.get("name", "N/A")

        if garmin_activity_name.startswith(tuple(sync_ignore_list)):
            print(f"Skipping Garmin activity name \"{garmin_activity_name}\" as it is in the ignore list.")
            continue

        if garmin_timestamp in strava_activities:
            strava_activity_name = strava_activities[garmin_timestamp].get("name", "N/A")
            if garmin_activity_name != strava_activity_name:
                print(f"Timestamp: {garmin_timestamp}, Garmin Name: \"{garmin_activity_name}\", Strvav Name: \"{strava_activity_name}\" (Names differ)")

                strava_id = strava_activities[garmin_timestamp].get("id")
                strava_update_activity_name(strava_client, strava_id, garmin_activity_name)


def env_pre_check():
    if not GARMIN_TOKENS_BASE64:
        print("GARMIN_TOKENS_BASE64 environment variable is not set.")
        exit(1)
    if not os.getenv("STRAVA_CLIENT_ID"):
        print("STRAVA_CLIENT_ID environment variable is not set.")
        exit(1)
    if not os.getenv("STRAVA_CLIENT_SECRET"):
        print("STRAVA_CLIENT_SECRET environment variable is not set.")
        exit(1)
    if not os.getenv("SILENCE_TOKEN_WARNINGS"):
        print("SILENCE_TOKEN_WARNINGS environment variable is not set.")
        exit(1)
    if not os.path.exists(STRAVA_TOKEN_PATH):
        print(f"Strava token file \"{STRAVA_TOKEN_PATH}\" does not exist.")
        exit(1)
    if not os.path.exists(SYNC_IGNORE):
        print(f"Sync ignore file \"{SYNC_IGNORE}\" does not exist.")
        exit(1)


if __name__ == "__main__":
    try:
        env_pre_check()

        # Initialize Garmin API
        garmin_api = init_garmin_api()
        if not garmin_api:
            print("Fail to init Garmin API")
            exit(1)

        # Initialize Strava client
        strava_client = init_strava_client()
        if not strava_client:
            print("Fail to init Strava client")
            exit(1)
        athlete = strava_client.get_athlete()
        print(f"Hi, {athlete.firstname} Welcome to stravalib!")

        # Define date range for activities (last 7 days)
        before_datetime_utc = datetime.now(timezone.utc)
        after_datetime_utc = before_datetime_utc - timedelta(days=7)
        
        # Get Garmin activities
        success, garmin_activities = get_garmin_activities(garmin_api, after_datetime_utc, before_datetime_utc)

        if success and garmin_activities:
            print(f"Found {len(garmin_activities)} activities from Garmin")

            # Get Strava activities
            success, strava_activities = get_strava_activities(strava_client, after_datetime_utc, before_datetime_utc)

            if success and strava_activities:
                print(f"Found {len(strava_activities)} activities from Strava")
                # Sync activity names from Garmin to Strava
                sync_name_from_garmin_to_strava(garmin_activities, strava_activities, strava_client)
            else:
                if not success:
                    print("❌ Failed to get Strava activities.")
                else:
                    print("ℹ️ No Strava activities found to sync.")
        else:
            if not success:
                print("❌ Failed to get Garmin activities.")
            else:
                print("ℹ️ No Garmin activities found to sync.")
    except Exception as e:
        print(f"Error when syncing activity name: {e}")
        exit(1)