#!/usr/bin/env python

import asyncio
import json
import os
import urllib.request

from playwright.async_api import Playwright, async_playwright


async def download_ndc_index_zip(playwright: Playwright, output_path: str):
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto("https://data.gov.tw/dataset/6099")

    async with page.expect_download() as download_info:
        await page.get_by_role("button", name="ZIP").click()
    download = await download_info.value
    await download.save_as(output_path)

    await browser.close()


def send_line_message(token: str, to: str, text: str):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    data = {
        "to": to,
        "messages": [{"type": "text", "text": text}],
    }
    req = urllib.request.Request(
        url, data=json.dumps(data).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(req) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        print(f"Error sending LINE message to {to}: {e}")
        return None


async def main():
    import zipfile
    from pathlib import Path

    zip_path = Path("/tmp/ndc_index.zip")
    extract_dir = Path("/tmp/ndc_index")
    csv_filename = "景氣指標與燈號.csv"
    csv_path = extract_dir / csv_filename

    # download ndc index zip
    async with async_playwright() as playwright:
        try:
            await download_ndc_index_zip(playwright, str(zip_path))
        except Exception as e:
            print(f"Error downloading ZIP: {e}")
            return

    # unzip the zip file
    try:
        if not zip_path.exists():
            print(f"Error: {zip_path} does not exist.")
            return

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
    except Exception as e:
        print(f"Error unzipping file: {e}")
        return

    # read the csv file
    try:
        if not csv_path.exists():
            # Sometimes the filename in zip might be different or nested
            # Let's look for any csv file if the specific one isn't found
            csv_files = list(extract_dir.glob("*.csv"))
            if csv_files:
                csv_path = csv_files[0]
            else:
                print(f"Error: Could not find CSV file in {extract_dir}")
                return

        import csv

        valid_rows = []
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Filter out rows where signal or score is missing (marked as '-')
                if row["景氣對策信號"] != "-" and row["景氣對策信號綜合分數"] != "-":
                    # Convert score to int for consistency
                    try:
                        row["景氣對策信號綜合分數"] = int(row["景氣對策信號綜合分數"])
                        valid_rows.append(row)
                    except ValueError:
                        continue

        if not valid_rows:
            print("Error: No valid data found in CSV.")
            return

        # Sort by Date descending to get the latest row
        valid_rows.sort(key=lambda x: x["Date"], reverse=True)
        latest_row = valid_rows[0]
        latest_date = latest_row["Date"]
        latest_signal = latest_row["景氣對策信號"]
        latest_signal_score = latest_row["景氣對策信號綜合分數"]

        output = f"""
## NDC Index Summary
- **Latest Date**: {latest_date}
- **Latest Signal**: {latest_signal}
- **Latest Signal Score**: {latest_signal_score}
"""
        print(output.strip())

        # GitHub Actions Step Summary
        github_step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if github_step_summary:
            with open(github_step_summary, "a") as f:
                f.write(output)

        import json
        import subprocess

        new_data = {
            "latest_date": str(latest_date),
            "latest_signal": latest_signal,
            "latest_signal_score": int(latest_signal_score),
        }

        ndc_index_env = os.environ.get("NDC_INDEX")
        should_update = False

        if not ndc_index_env:
            print(
                "NDC_INDEX variable not found in environment, assuming first run or missing config."
            )
            should_update = True
        else:
            try:
                old_data = json.loads(ndc_index_env)
                if (
                    old_data.get("latest_date") != new_data["latest_date"]
                    or old_data.get("latest_signal") != new_data["latest_signal"]
                    or old_data.get("latest_signal_score")
                    != new_data["latest_signal_score"]
                ):
                    print("Data has changed, updating NDC_INDEX.")
                    should_update = True
                else:
                    print("Data is up to date, no action needed.")
            except json.JSONDecodeError:
                print("Error decoding NDC_INDEX JSON, will attempt to overwrite.")
                should_update = True

        if should_update:
            new_data_json = json.dumps(new_data, ensure_ascii=False)
            print(f"Update planned: {new_data_json}")

            # Prepare LINE message
            old_data_str = "None"
            if ndc_index_env:
                try:
                    old_data_json = json.loads(ndc_index_env)
                    old_signal_score = old_data_json.get("latest_signal_score")
                    old_data_str = f"{old_data_json.get('latest_date')} ({old_data_json.get('latest_signal')}, 分數: {old_signal_score})"
                except Exception:
                    old_data_str = ndc_index_env

            new_signal_score = new_data.get("latest_signal_score")

            trend_icon = ""
            if "old_signal_score" in locals():
                if old_signal_score < new_signal_score:
                    trend_icon = " 📈"
                elif old_signal_score > new_signal_score:
                    trend_icon = " 📉"

            new_data_str = f"{new_data['latest_date']} ({new_data['latest_signal']}, 分數: {new_signal_score})"
            line_message = f"🔔 國發會景氣對策信號 更新！\n\n上次: {old_data_str}\n這次: {new_data_str}{trend_icon}"

            line_token = os.environ.get("LINE_CH_ACCESS_TOKEN")
            line_users = [
                os.environ.get("LINE_EDWARD_ID"),
                os.environ.get("LINE_JOEY_ID"),
            ]
            line_users = [u for u in line_users if u]

            if line_token and line_users:
                print(f"Sending LINE notifications to {len(line_users)} users.")
                for user_id in line_users:
                    send_line_message(line_token, user_id, line_message)
            else:
                print("LINE notification skipped: Missing token or user IDs.")

            # Check if we are in GHA to decide whether to run gh command
            if os.environ.get("GITHUB_ACTIONS"):
                try:
                    # Use gh variable set to update the repo variable
                    # Note: This requires the GHA token to have write permissions for repository variables
                    subprocess.run(
                        ["gh", "variable", "set", "NDC_INDEX", "--body", new_data_json],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    print("Successfully updated NDC_INDEX variable via gh CLI.")
                except subprocess.CalledProcessError as e:
                    print(f"Failed to update NDC_INDEX variable: {e.stderr}")
            else:
                print("Not running in GitHub Actions, skipping GH CLI update.")

    except Exception as e:
        print(f"Error processing CSV: {e}")
    finally:
        # Cleanup
        if zip_path.exists():
            zip_path.unlink()
        if extract_dir.exists():
            import shutil

            shutil.rmtree(extract_dir)


if __name__ == "__main__":
    asyncio.run(main())
