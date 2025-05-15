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

# Load environment variables if defined
email = os.getenv("GARMIN_EMAIL")
password = os.getenv("GARMIN_PASSWORD")
tokenstore = os.getenv("GARMIN_TOKENS") or "~/.garminconnect"
tokenstore_base64 = os.getenv("GARMIN_TOKENS_BASE64") or "~/.garminconnect_base64"

last_synced_date = os.getenv("GARMIN_STEPS_LAST_SYNCED_DATE") # "2025-05-13" in GMT+0800
new_last_synced_date_file = "./new_last_synced_date.txt"

def get_credentials():
    """Get user credentials."""

    email = input("Login e-mail: ")
    password = getpass("Enter password: ")

    return email, password

def get_mfa():
    """Get MFA."""

    return input("MFA one-time code: ")

def init_api(email, password):
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

def is_one_day_steps_are_all_synced(steps_data):
    """
    Check if all steps data are synced for one day
        :param steps_data: steps data (list of dict)
        :return: True if all steps data are synced, False otherwise
    """
    if not steps_data:
        return False
    
    # check startGMT of the last entry is 23:45:00 in GMT+0800
    last_entry = steps_data[-1]
    last_entry_startGMT = datetime.strptime(
        last_entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f"
    ).replace(tzinfo=timezone.utc)
    last_entry_startGMT = last_entry_startGMT.astimezone(timezone(timedelta(hours=8)))
    if last_entry_startGMT.hour != 23 or last_entry_startGMT.minute != 45:
        return False

    return True
    
def filter_steps_data(steps_data):
    """
    filter steps data, keep only the items where steps is not 0,
        and convert time to milliseconds.
    
    :param steps_data: raw steps data (list of dict)
    :return: filtered steps data (list of dict)
    """
    filtered_data = []

    for entry in steps_data:
        if entry["steps"] > 0:
            # convert startGMT and endGMT to milliseconds
            
            startGMTMillis = int(
                datetime.strptime(entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f")
                .replace(tzinfo=timezone.utc)
                .timestamp() * 1000
            )
            endGMTMillis = int(
                datetime.strptime(entry["endGMT"], "%Y-%m-%dT%H:%M:%S.%f")
                .replace(tzinfo=timezone.utc)
                .timestamp() * 1000
            )

            filtered_data.append({
                "startGMTMillis": startGMTMillis,
                "endGMTMillis": endGMTMillis,
                "steps": entry["steps"]
            })

    return filtered_data

if __name__ == "__main__":
    try:
        # check GARMIN_STEPS_LAST_SYNCED_DATE environment variable
        if not last_synced_date:
            print("GARMIN_STEPS_LAST_SYNCED_DATE environment variable is not set.")
            exit(1)
        # check GARMIN_TOKENS_BASE64 environment variable
        if not tokenstore_base64:
            print("GARMIN_TOKENS_BASE64 environment variable is not set.")
            exit(1)

        api = init_api(email, password)
        if not api:
            print("Fail to init Garmin API")
            exit(1)

        # Get the last synced date
        last_synced_date = datetime.strptime(last_synced_date, "%Y-%m-%d").date()

        current_date = last_synced_date
        steps_data = []
        while current_date <= datetime.now(tz=timezone(timedelta(hours=8))).date():
            steps_data = get_steps_by_date(api, current_date)
            if not steps_data:
                print(f"No steps data found for {current_date}.")
                break

            print(f"===============================")
            print(f"Steps data for {current_date}")
            print(json.dumps(steps_data, indent=4))
            filtered_steps = filter_steps_data(steps_data)
            print(json.dumps(filtered_steps, indent=4))
            # TODO: sync to google fit
            
            if not is_one_day_steps_are_all_synced(steps_data):
                print(f"Steps data for {current_date} are not all synced.")
                break

            current_date += timedelta(days=1)

        # write the new last synced date to file
        print(f"wirte {current_date} to {new_last_synced_date_file}")
        with open(new_last_synced_date_file, "w") as f:
            f.write(current_date.strftime("%Y-%m-%d"))
    except Exception as e:
        print(f"Error when getting steps: {e}")
