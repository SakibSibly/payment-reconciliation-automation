import re
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import Playwright, sync_playwright, expect
from decouple import config


base_url = config("OWN_URL")
username = config("OWN_USER")
password = config("OWN_PASS")
previous_days = config("PREVIOUS_DAYS", default=1, cast=int)
target_date = (datetime.now() - timedelta(days=previous_days)).strftime("%Y-%m-%d")

download_dir = Path("downloaded_files") / "own"
download_dir.mkdir(parents=True, exist_ok=True)


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(base_url)
    page.get_by_role("textbox", name="Username").click()
    page.get_by_role("textbox", name="Username").fill(username)
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").fill(password)
    page.get_by_role("button", name="LOGIN").click()
    page.get_by_role("link", name="Reports", exact=True).click()
    page.get_by_role("link", name="MQ Sure").click()
    page.goto(f"{base_url}/mqsure-reports")
    page.get_by_role("link", name="MQ Payment List").click()
    page.get_by_role("textbox", name="From Date").fill(target_date)
    page.get_by_role("textbox", name="To Date").fill(target_date)
    page.get_by_role("button", name="Download").click()
    with page.expect_download() as download_info:
        page.goto(f"{base_url}/mqsurereports/Paymentlist-reconcile")
    download = download_info.value
    download.save_as(str(download_dir / f"mq_payment_list_{target_date}{Path(download.suggested_filename).suffix}"))
    page.get_by_role("link", name="Reports", exact=True).click()
    page.get_by_role("link", name="MQ Sure").click()
    page.goto(f"{base_url}/mqsure-reports")
    page.get_by_role("link", name="Orbit Maxim Payment List").click()
    page.get_by_role("textbox", name="From Date").fill(target_date)
    page.get_by_role("textbox", name="To Date").fill(target_date)
    with page.expect_download() as download1_info:
        page.get_by_role("button", name="Download").click()
    download1 = download1_info.value
    download1.save_as(str(download_dir / f"orbit_maxim_payment_list_{target_date}{Path(download1.suggested_filename).suffix}"))
    page.get_by_role("link", name="Reports", exact=True).click()
    page.get_by_role("link", name="MQ Sure").click()
    page.goto(f"{base_url}/mqsure-reports")
    page.get_by_role("link", name="Race Maxim Payment List").click()
    page.get_by_role("textbox", name="From Date").fill(target_date)
    page.get_by_role("textbox", name="To Date").fill(target_date)
    with page.expect_download() as download2_info:
        page.get_by_role("button", name="Download").click()
    download2 = download2_info.value
    download2.save_as(str(download_dir / f"race_maxim_payment_list_{target_date}{Path(download2.suggested_filename).suffix}"))

    # ---------------------
    context.close()
    browser.close()


def run_billing_system():
    print("🚀 Starting Billing System Automation...")

    with sync_playwright() as playwright:
        run(playwright)

    print("✅ Billing System Automation Completed!")


if __name__ == "__main__":
    run_billing_system()