#!/usr/bin/env python

import asyncio
from playwright.async_api import async_playwright, Playwright


async def download_ndc_index_zip(playwright: Playwright, output_path: str):
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto("https://data.gov.tw/dataset/6099")

    async with page.expect_download() as download_info:
        await page.get_by_role("button", name="ZIP").click()
    download = await download_info.value
    await download.save_as(output_path)

    await browser.close()


async def main():
    import os
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

        # 讀取 GHA 的 variables "NDC_INDEX", 如果有讀到(會是一個 JSON 格式)
        # 比較 latest_date, latest_signal, latest_signal_score 與 NDC_INDEX 中的值
        # 如果有不同，則將 latest_date, latest_signal, latest_signal_score 變成一個 JSON 存入 GHA 的 variables
        # 如果沒有不同就不動作
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
