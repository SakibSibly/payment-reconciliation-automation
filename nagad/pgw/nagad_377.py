from pathlib import Path
from datetime import datetime, timedelta
from decouple import config
from playwright.sync_api import Playwright, sync_playwright


def run(playwright: Playwright) -> None:
    username = config("NAGAD_USER_05")
    password = config("NAGAD_PASS_05")
    login_url = config("NAGAD_URL")
    previous_days = config("PREVIOUS_DAYS", default=1, cast=int)
    target_dt = datetime.now() - timedelta(days=previous_days)
    target_date_display = target_dt.strftime("%d-%m-%Y")
    target_day = str(target_dt.day)

    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(login_url)
    page.get_by_role("textbox", name="user name").click()
    page.get_by_role("textbox", name="user name").fill(username)
    page.get_by_role("textbox", name="password").click()
    page.get_by_role("textbox", name="password").fill(password)
    page.get_by_role("button", name="Log In").click()
    page.get_by_role("link", name=" Payment ").click()
    page.get_by_role("link", name=" Online Payment History").click()
    page.wait_for_load_state("domcontentloaded")
    page.locator(".input-group-text").first.click()
    try:
        page.get_by_text(target_day, exact=True).click(timeout=5000)
    except Exception:
        page.get_by_text("14").click()
    page.locator("div:nth-child(2) > .input-group > .input-group-append > .input-group-text > .fa").click()
    try:
        page.get_by_text(target_day, exact=True).click(timeout=5000)
    except Exception:
        page.get_by_text("14").click()
    page.get_by_role("button", name="Search", exact=True).click()
    with page.expect_download() as download_info:
        with page.expect_popup() as page1_info:
            page.get_by_role("button", name=" Excel").click()
        page1 = page1_info.value
    download = download_info.value

    output_dir = Path("downloaded_files") / "nagad"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"payment_history_377_{target_date_display}{Path(download.suggested_filename).suffix}"
    download.save_as(str(output_file))
    page1.close()

    print(f"Saved Nagad PGW 377 history: {output_file}")

    # ---------------------
    context.close()
    browser.close()


def run_nagad_377():
    print("🚀 Starting Nagad 377 Automation...")
    with sync_playwright() as playwright:
        run(playwright)
    print("✅ Nagad 377 Automation Completed!")


if __name__ == "__main__":
    run_nagad_377()
