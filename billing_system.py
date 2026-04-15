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
    page.set_default_timeout(60000)
    page.set_default_navigation_timeout(60000)

    def open_mqsure_reports() -> None:
        # Menu rendering can lag after login when this script is orchestrated from another module.
        # Try normal menu navigation first, then fall back to direct URL.
        try:
            page.get_by_role("link", name="Reports", exact=True).click(timeout=10000)
            page.get_by_role("link", name="MQ Sure").click(timeout=10000)
        except Exception:
            pass
        page.goto(f"{base_url}/mqsure-reports")

    page.goto(base_url)
    page.get_by_role("textbox", name="Username").click()
    page.get_by_role("textbox", name="Username").fill(username)
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").fill(password)
    page.get_by_role("button", name="LOGIN").click()
    page.wait_for_load_state("domcontentloaded")
    open_mqsure_reports()
    page.get_by_role("link", name="MQ Payment List").click()
    page.get_by_role("textbox", name="From Date").fill(target_date)
    page.get_by_role("textbox", name="To Date").fill(target_date)
    page.get_by_role("button", name="Download").click()
    with page.expect_download(timeout=60000) as download_info:
        page.goto(f"{base_url}/mqsurereports/Paymentlist-reconcile")
    download = download_info.value
    download.save_as(str(download_dir / f"mq_payment_list_{target_date}{Path(download.suggested_filename).suffix}"))
    open_mqsure_reports()
    page.get_by_role("link", name="Orbit Maxim Payment List").click()
    page.get_by_role("textbox", name="From Date").fill(target_date)
    page.get_by_role("textbox", name="To Date").fill(target_date)
    with page.expect_download(timeout=60000) as download1_info:
        page.get_by_role("button", name="Download").click()
    download1 = download1_info.value
    download1.save_as(str(download_dir / f"orbit_maxim_payment_list_{target_date}{Path(download1.suggested_filename).suffix}"))
    open_mqsure_reports()
    page.get_by_role("link", name="Race Maxim Payment List").click()
    page.get_by_role("textbox", name="From Date").fill(target_date)
    page.get_by_role("textbox", name="To Date").fill(target_date)
    with page.expect_download(timeout=60000) as download2_info:
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