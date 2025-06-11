import base64
import os
import json
from garminconnect import Garmin
from datetime import datetime, timezone, timedelta
from getpass import getpass

import requests
from garth.exc import GarthHTTPError
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError
)

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Load environment variables if defined
email = os.getenv("GARMIN_EMAIL")
password = os.getenv("GARMIN_PASSWORD")
tokenstore = os.getenv("GARMIN_TOKENS") or "~/.garminconnect"
tokenstore_base64 = os.getenv("GARMIN_TOKENS_BASE64")

google_authorized_user_json_base64 = os.getenv("GOOGLE_AUTH_USER_JSON_BASE64")
refreshed_auth_user_json_base64_file = "./refreshed_auth_user_json_base64_file.txt"

last_startGMT = os.getenv("GARMIN_STEPS_LAST_STARTGMT") # "2025-05-15T20:30:00.0"
new_last_startGMT_file = "./new_last_startGMT_file.txt"

GOOGLE_FIT_API_SCOPES = ['https://www.googleapis.com/auth/fitness.activity.write']

UTC_TIMEZONE = timezone.utc
TAIPEI_TIMEZONE = timezone(timedelta(hours=8))

def get_credentials():
    """Get user credentials."""

    email = input("Login e-mail: ")
    password = getpass("Enter password: ")

    return email, password

def get_mfa():
    """Get MFA."""

    return input("MFA one-time code: ")

def init_garmin_api(email, password):
    """Initialize Garmin API with your credentials."""
    try:
        # Using Oauth1 and Oauth2 tokens from base64 encoded string
        print(
            "Trying to login to Garmin Connect using token data from GARMIN_TOKENS_BASE64 env...\n"
        )

        garmin = Garmin()
        garmin.login(tokenstore_base64)

    except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError):
        # Session is expired. You'll need to log in again
        print(
            "Login tokens not present, login with your Garmin Connect credentials to generate them.\n"
            f"They will be stored in '{tokenstore}' for future use.\n"
        )
        try:
            # Ask for credentials if not set as environment variables
            if not email or not password:
                email, password = get_credentials()

            garmin = Garmin(
                email=email, password=password, is_cn=False, return_on_mfa=True
            )
            result1, result2 = garmin.login()
            if result1 == "needs_mfa":  # MFA is required
                mfa_code = get_mfa()
                garmin.resume_login(result2, mfa_code)

            # Save Oauth1 and Oauth2 token files to directory for next login
            garmin.garth.dump(tokenstore)
            print(
                f"Oauth tokens stored in '{tokenstore}' directory for future use. (first method)\n"
            )

            # Encode Oauth1 and Oauth2 tokens to base64 string and safe to file for next login (alternative way)
            token_base64 = garmin.garth.dumps()
            dir_path = os.path.expanduser(tokenstore_base64)
            with open(dir_path, "w") as token_file:
                token_file.write(token_base64)
            print(
                f"Oauth tokens encoded as base64 string and saved to '{dir_path}' file for future use. (second method)\n"
            )

            # Re-login Garmin API with tokens
            garmin.login(tokenstore)
        except (
            FileNotFoundError,
            GarthHTTPError,
            GarminConnectAuthenticationError,
            requests.exceptions.HTTPError,
        ) as err:
            print(f"Initialize Garmin API error: {err}")
            return None

    return garmin

def get_steps_by_date(api, date):
    """
    Get steps by date
        :param api: Garmin API instance
        :param date: _Date object
        :return: steps data (list of dict)
    """
    try:
        steps_data = api.get_steps_data(date.isoformat())
        return steps_data
    except Exception as e:
        print(f"Error when getting steps: {e}")

def parse_datetime_with_timezone(date_str, format_str="%Y-%m-%dT%H:%M:%S.%f", tz=UTC_TIMEZONE):
    """
    Parse a datetime string and ensure it has the correct timezone.
    :param date_str: The datetime string to parse.
    :param format_str: The format of the datetime string.
    :param tz: The timezone to apply if not already present.
    :return: A timezone-aware datetime object.
    """
    try:
        dt = datetime.strptime(date_str, format_str)
        return dt.replace(tzinfo=tz)
    except ValueError as e:
        print(f"Error parsing datetime '{date_str}': {e}")
        return None

def is_one_day_steps_are_all_done(steps_data):
    """
    Check if all steps data are synced for one day.
    :param steps_data: steps data (list of dict)
    :return: True if all steps data are synced, False otherwise
    """
    if not steps_data:
        return False

    # Check startGMT of the last entry is 23:45:00 in UTC+0800
    last_entry = steps_data[-1]
    try:
        last_entry_startGMT = parse_datetime_with_timezone(last_entry["startGMT"])
        if not last_entry_startGMT:
            return False

        last_entry_startUTC8 = last_entry_startGMT.astimezone(TAIPEI_TIMEZONE)
        if last_entry_startUTC8.hour != 23 or last_entry_startUTC8.minute != 45:
            return False
    except Exception as e:
        print(f"Unexpected error in is_one_day_steps_are_all_synced: {e}")
        return False

    return True

def filter_steps_data(steps_data, last_startGMT_date):
    """
    Filter steps data, keep only the items where steps is not 0,
    and convert time to milliseconds.
    :param steps_data: raw steps data (list of dict)
    :param last_startGMT_date: The last synced datetime in UTC.
    :return: filtered steps data (list of dict)
    """
    filtered_data = []
    last_startGMT_seconds = int(last_startGMT_date.timestamp())
    for entry in steps_data:
        try:
            startGMT = parse_datetime_with_timezone(entry["startGMT"])
            endGMT = parse_datetime_with_timezone(entry["endGMT"])
            if not startGMT or not endGMT:
                continue

            startGMTSeconds = int(startGMT.timestamp())
            if entry["steps"] > 0 and startGMTSeconds > last_startGMT_seconds:
                # Convert startGMT and endGMT to milliseconds
                startGMTMillis = startGMTSeconds * 1000
                endGMTMillis = int(endGMT.timestamp() * 1000)

                filtered_data.append({
                    "startGMTMillis": startGMTMillis,
                    "endGMTMillis": endGMTMillis,
                    "steps": entry["steps"]
                })
        except Exception as e:
            print(f"Error filtering steps data for entry {entry}: {e}")

    return filtered_data

def load_auth_user_credentials(auth_user_info):
    print("Trying to load credential from auth user info...\n")

    credentials = Credentials.from_authorized_user_info(auth_user_info, scopes=GOOGLE_FIT_API_SCOPES)
    refreshed = False

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                print("auth user credential expired, try to refresh...")
                credentials.refresh(Request())
                print("Refresh done")
                refreshed = True
            except Exception as e:
                print(f"Refresh failed: {e}")
                credentials = None

    return credentials, refreshed

def init_google_fit_api(auth_user_json):
    """
    Initialize Google Fit API
    :return: Google Fit API instance
    """
    try:
        # Load auth user credentials
        credentials, refreshed = load_auth_user_credentials(auth_user_json)
        if not credentials:
            print("Failed to load auth user credentials.")
            return None

        # If credentials were refreshed, save the new credentials to file
        if refreshed:
            print("Save refreshed auth user credentials to file...")
            with open(refreshed_auth_user_json_base64_file, "w") as f:
                f.write(base64.b64encode(credentials.to_json().encode("utf-8")).decode("utf-8"))
            print(f"Refreshed auth user credentials saved to {refreshed_auth_user_json_base64_file}")

        # Initialize Google Fit API
        print("Initializing Google Fit API...")
        service = build('fitness', 'v1', credentials=credentials, static_discovery=False)

        return service
    except Exception as e:
        print(f"Error initializing Google Fit API: {e}")
        return None

def create_or_get_google_fit_data_source(service, data_source_id_suffix="garmin-steps-syncer"):
    project_number_string = "453184793678"  # Google Cloud project number
    manufacturer = "EDJY Projects"
    model = "GarminConnectStepsSyncer"
    uid = f"vdev-{data_source_id_suffix}"
    data_stream_name = "GarminConnectStepsSyncer"

    # update dataStreamId format
    data_stream_id = f"derived:com.google.step_count.delta:{project_number_string}:{manufacturer}:{model}:{uid}:{data_stream_name}"

    data_source_body = {
        "dataStreamName": data_stream_name,
        "type": "derived",
        "application": {
            "detailsUrl": "http://example.com/python_fit_app",
            "name": "Garmin Connect Steps Syncer",
            "version": "1.0"
        },
        "dataType": {
            "name": "com.google.step_count.delta"
        },
        "device": {
            "manufacturer": manufacturer,
            "model": model,
            "type": "unknown",
            "uid": uid,
            "version": "1.0"
        },
        "dataStreamId": data_stream_id
    }

    try:
        print(f"Trying to get data source: {data_stream_id}...")
        datasource = service.users().dataSources().get(userId='me', dataSourceId=data_stream_id).execute()
        print(f"Found existing data source: {datasource.get('dataStreamId')}")
        return datasource
    except HttpError as e:
        if e.resp.status == 404:
            print("Data source not exist, try to create a new data source...")
            try:
                datasource = service.users().dataSources().create(userId='me', body=data_source_body).execute()
                print(f"Data source create OK: {datasource.get('dataStreamId')}")
                return datasource
            except HttpError as err_create:
                print(f"HTTP error when creating data source: {err_create}")
                print(f"Deatil error: {err_create.content.decode()}")
                return None
            except Exception as ex_create:
                print(f"Unexpected error when creating data source: {ex_create}")
                return None
        else:
            print(f"Unexpected HTTP error when getting data sourcec: {e}")
            print(f"Deatil error: {e.content.decode()}")
            return None
    except Exception as e:
        print(f"Unexpected error when getting or creating data source: {e}")
        return None

def insert_steps_data_list(service, data_source_id, steps_data_list):

    data_point_set = []

    for entry in steps_data_list:
        data_point_set.append({
            "dataTypeName": "com.google.step_count.delta",
            "startTimeNanos": str(entry["startGMTMillis"] * 1000000),
            "endTimeNanos": str(entry["endGMTMillis"] * 1000000),
            "value": [
                {
                    "intVal": entry["steps"], # steps (integer)
                }
            ],
            "originDataSourceId": data_source_id
        })

    # create dataset ID
    # format of dataset ID: {startTimeNanos}-{endTimeNanos}
    # the ID is used to identify the dataset
    start_time_nanos = data_point_set[0]["startTimeNanos"]
    end_time_nanos = data_point_set[-1]["endTimeNanos"]
    dataset_id = f"{start_time_nanos}-{end_time_nanos}"

    # data dataset_body, include data source ID, start time, end time and data point set
    dataset_body = {
        "dataSourceId": data_source_id,
        "minStartTimeNs": str(start_time_nanos),
        "maxEndTimeNs": str(end_time_nanos),
        "point": data_point_set
    }

    try:
        print(f"Writing data to data set: {dataset_id} (data source: {data_source_id})")
        service.users().dataSources().datasets().patch(
            userId='me',
            dataSourceId=data_source_id,
            datasetId=dataset_id,
            body=dataset_body
        ).execute()
        print(f"OK to write {len(data_point_set)} records to data set {dataset_id}。")
        start_time_millis = int(start_time_nanos) // 1000000
        end_time_millis = int(end_time_nanos) // 1000000
        print(f"Start time: {start_time_millis} ms, end time: {end_time_millis} ms")
    except HttpError as e:
        print(f"HTTP error when writing steps: {e}")
        print(f"Detail error: {e.content.decode()}")
    except Exception as e:
        print(f"Unexpected error when writing steps: {e}")

if __name__ == "__main__":
    try:
        # Check GARMIN_STEPS_LAST_STARTGMT environment variable
        if not last_startGMT:
            print("GARMIN_STEPS_LAST_STARTGMT environment variable is not set.")
            exit(1)

        # Convert last_startGMT to datetime in UTC
        last_startGMT_date = parse_datetime_with_timezone(last_startGMT)
        if not last_startGMT_date:
            print("Invalid GARMIN_STEPS_LAST_STARTGMT format.")
            exit(1)

        # Check GARMIN_TOKENS_BASE64 environment variable
        if not tokenstore_base64:
            print("GARMIN_TOKENS_BASE64 environment variable is not set.")
            exit(1)

        # Check GOOGLE_AUTH_USER_JSON_BASE64 environment variable
        if not google_authorized_user_json_base64:
            print("GOOGLE_AUTH_USER_JSON_BASE64 environment variable is not set.")
            exit(1)

        # Decode google_authorized_user_json_base64 base64 string
        google_authorized_user_json = json.loads(base64.b64decode(google_authorized_user_json_base64).decode("utf-8"))

        # Initialize Google Fit API
        google_fit_api = init_google_fit_api(google_authorized_user_json)
        if not google_fit_api:
            print("Fail to init Google Fit API")
            exit(1)

        # Get Google Fit data source
        google_fit_data_source = create_or_get_google_fit_data_source(google_fit_api)
        if not google_fit_data_source or 'dataStreamId' not in google_fit_data_source:
            print("Fail to create or get Google Fit data source")
            exit(1)
        google_fit_data_source_id = google_fit_data_source['dataStreamId']
        print(f"OK to get/create data source ID: {google_fit_data_source_id}")

        # Initialize Garmin API
        garmin_api = init_garmin_api(email, password)
        if not garmin_api:
            print("Fail to init Garmin API")
            exit(1)

        last_startUTC8_date = last_startGMT_date.astimezone(TAIPEI_TIMEZONE)
        current_date = last_startUTC8_date.date()
        steps_data = []
        while current_date <= datetime.now(tz=TAIPEI_TIMEZONE).date():
            steps_data = get_steps_by_date(garmin_api, current_date)
            if not steps_data:
                print(f"No steps data found for {current_date}.")
                break

            is_steps_are_all_done = is_one_day_steps_are_all_done(steps_data)

            filtered_steps = filter_steps_data(steps_data, last_startGMT_date)
            if not filtered_steps:
                if is_steps_are_all_done:
                    print(f"All steps data for {current_date} are already synced. Try next day.")
                    current_date += timedelta(days=1)
                    continue
                else:
                    print(f"No steps need to sync for {current_date}.")
                    break

            print(f"===============================")
            print(f"Steps need to sync for {current_date}")
            print(json.dumps(filtered_steps, indent=4))

            # Insert steps data to Google Fit
            insert_steps_data_list(google_fit_api, google_fit_data_source_id, filtered_steps)

            # Update last_startGMT_date to the last entry of steps data
            last_entry_startGMT = parse_datetime_with_timezone(steps_data[-1]["startGMT"])
            if last_entry_startGMT:
                last_startGMT_date = last_entry_startGMT

            if not is_steps_are_all_done:
                print(f"Steps data for {current_date} are not all synced.")
                break

            current_date += timedelta(days=1)

        # Write the new last synced date to file
        print(f"Write {last_startGMT_date} to {new_last_startGMT_file}")
        with open(new_last_startGMT_file, "w") as f:
            f.write(last_startGMT_date.strftime("%Y-%m-%dT%H:%M:%S.0"))
    except Exception as e:
        print(f"Error when getting steps: {e}")
