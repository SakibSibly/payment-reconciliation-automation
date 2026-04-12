from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from seleniumbase import sb_cdp
from decouple import config
from datetime import date, timedelta
import random
from pathlib import Path

def run_bkash():
    print("🚀 Starting bKash Automation...")

    def human_wait(page, min_ms=700, max_ms=1800):
        page.wait_for_timeout(random.randint(min_ms, max_ms))

    def click_with_jitter(page, locator, label, retries=3):
        for attempt in range(1, retries + 1):
            try:
                locator.first.wait_for(state="visible", timeout=20000)
                human_wait(page, 900, 2500)
                locator.first.scroll_into_view_if_needed()
                locator.first.click(timeout=10000)
            except PlaywrightTimeoutError:
                if attempt == retries:
                    raise RuntimeError(f"{label} was not visible/clickable in time.")
                cooldown_ms = random.randint(3000, 9000)
                print(f"{label} not ready yet. Retrying in {cooldown_ms/1000:.1f}s...")
                page.wait_for_timeout(cooldown_ms)
                continue

            human_wait(page, 700, 1800)

            body_text = page.locator("body").inner_text().lower()
            if "too many request" in body_text or "incident will be recorded" in body_text:
                if attempt == retries:
                    raise RuntimeError(f"Rate limit triggered while clicking {label}.")
                cooldown_ms = random.randint(20000, 45000)
                print(f"Rate limit detected on {label}. Cooling down {cooldown_ms/1000:.1f}s...")
                page.wait_for_timeout(cooldown_ms)
                continue

            return

        raise RuntimeError(f"Failed to click {label} after {retries} attempts.")

    # Path to the browser
    # Mine is Brave in windows change accordingly
    BRAVE_PATHS = {
        "linux": "/usr/bin/brave-browser",
        "windows": "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe",
        "mac": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    }

    sb = sb_cdp.Chrome(
        locale="en",
        binary_location=BRAVE_PATHS["windows"],
    )

    endpoint_url = sb.get_endpoint_url()
    URL = config("BKASH_PGW_URL")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint_url)
        page = browser.contexts[0].pages[0]
        page.goto(URL)
        page.wait_for_timeout(3000)
        page.fill('input[name="email"]', config("BKASH_PGW_USER"))
        page.wait_for_timeout(2000)
        page.fill('input[name="password"]', config("BKASH_PGW_PASS"))

        page.wait_for_timeout(2000)

        sb.solve_captcha()
        page.wait_for_timeout(2000)


        login_btn = page.locator('button:has-text("Log In")')
        login_btn.click()

        page.wait_for_url("**/dashboard**", timeout=15000)
        
        page.wait_for_timeout(1000)
        report_li = page.locator('li:has-text("Reports")')
        report_li.click()

        page.wait_for_timeout(1000)
        detailed_report_li = page.locator('a:has-text("Detailed Report")')
        detailed_report_li.click()

        page.wait_for_url("**/reports/detailed-reports**", timeout=15000)

        previous_days_btn = page.get_by_role("button", name="Previous Days", exact=True)
        today_btn = page.get_by_role("button", name="Today", exact=True)

        previous_days_btn.wait_for(state="visible", timeout=15000)
        previous_days_btn.scroll_into_view_if_needed()

        def is_previous_days_selected() -> bool:
            previous_class = previous_days_btn.get_attribute("class") or ""
            today_class = today_btn.get_attribute("class") or ""
            previous_selected = "border-primary-500" in previous_class and "bg-primary-100" in previous_class
            today_deselected = "border-gray-300" in today_class and "bg-white" in today_class
            return previous_selected and today_deselected

        # Retry with randomized wait and backoff to reduce rate-limit/anti-bot responses.
        for attempt in range(1, 4):
            if is_previous_days_selected():
                break

            human_wait(page, 1200, 3200)
            previous_days_btn.click(timeout=10000)
            human_wait(page, 1000, 2500)

            if is_previous_days_selected():
                break

            body_text = page.locator("body").inner_text().lower()
            if "too many request" in body_text or "incident will be recorded" in body_text:
                cooldown_ms = random.randint(20000, 45000)
                print(f"Rate limit warning detected. Cooling down for {cooldown_ms/1000:.1f}s before retry {attempt + 1}...")
                page.wait_for_timeout(cooldown_ms)

        try:
            page.wait_for_function(
                """() => {
                    const previousBtn = [...document.querySelectorAll('button')]
                        .find((btn) => btn.textContent?.trim() === 'Previous Days');
                    const todayBtn = [...document.querySelectorAll('button')]
                        .find((btn) => btn.textContent?.trim() === 'Today');

                    if (!previousBtn || !todayBtn) return false;

                    const previousClass = previousBtn.className || '';
                    const todayClass = todayBtn.className || '';

                    const previousSelected = previousClass.includes('border-primary-500') && previousClass.includes('bg-primary-100');
                    const todayDeselected = todayClass.includes('border-gray-300') && todayClass.includes('bg-white');

                    return previousSelected && todayDeselected;
                }""",
                timeout=12000,
            )
        except PlaywrightTimeoutError:
            # One final click path via JS events in case a CSS overlay swallows native clicks.
            previous_days_btn.evaluate(
                """(el) => {
                    el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                }"""
            )
            human_wait(page, 1200, 3000)

            if is_previous_days_selected():
                pass
            else:
                previous_class = previous_days_btn.get_attribute("class")
                today_class = today_btn.get_attribute("class")
                raise RuntimeError(
                    "Previous Days did not become active. "
                    f"Previous Days class: {previous_class}; Today class: {today_class}"
                )

        # page.wait_for_timeout(60000)



        # Force yesterday-only range to avoid pulling older historical data.
        date_format = config("DATE_FORMAT", default="%d/%m/%Y")

        yesterday = date.today() - timedelta(days=1)
        date_range_value = f"{yesterday.strftime(date_format)} - {yesterday.strftime(date_format)}"

        date_range_input = page.locator('input[name="displayDateRange"]')
        date_range_input.wait_for(state="visible", timeout=15000)
        date_range_input.evaluate("el => el.removeAttribute('readonly')")
        date_range_input.fill(date_range_value)
        date_range_input.dispatch_event("input")
        date_range_input.dispatch_event("change")
        page.keyboard.press("Enter")

        # Use text/CSS fallback because strict role+exact name can fail in Quasar dropdown buttons.
        download_btn = page.locator("div.card-header button:has-text('Download')").first
        click_with_jitter(page, download_btn, "Download")

        excel_btn = page.locator("text=Download Excel").last
        click_with_jitter(page, excel_btn, "Download Excel")

        status_ready = False
        max_status_checks = 3
        check_interval_ms = 5000
        download_action = page.locator(
            "table.mr-table tbody button:has-text('Download Report'), "
            "table.mr-table tbody span:has-text('Download Report'), "
            "table.mr-table tbody a:has-text('Download Report')"
        ).first

        # Move to Download Progress once, then poll with refresh + search.
        track_status_btn = page.locator("button:has-text('Track Status')").first
        click_with_jitter(page, track_status_btn, "Track Status")
        page.wait_for_url("**/reports/download-progress**", timeout=30000)

        for check in range(1, max_status_checks + 1):
            # Always refresh first so we read latest processing state from server.
            page.reload(wait_until="domcontentloaded")
            human_wait(page, 1800, 4200)

            # Focus the first filter action container before searching.
            action_container = page.locator("div.flex.items-center.space-x-2").first
            action_container.wait_for(state="visible", timeout=20000)
            action_container.evaluate(
                """(el) => {
                    el.scrollIntoView({ block: 'center' });
                    if (el.tabIndex < 0) el.tabIndex = 0;
                    el.focus();
                }"""
            )

            search_btn = action_container.locator("button").first
            click_with_jitter(page, search_btn, "Download Progress Search")

            try:
                download_action.wait_for(state="visible", timeout=15000)
                status_ready = True
                break
            except PlaywrightTimeoutError:
                if check == max_status_checks:
                    break
                print(
                    f"Report not ready yet (check {check}/{max_status_checks}). "
                    f"Waiting {check_interval_ms/1000:.0f}s before next refresh..."
                )
                page.wait_for_timeout(check_interval_ms)

        if not status_ready:
            raise RuntimeError(
                "Report was not ready after refresh checks. "
                "Increase BKASH_STATUS_MAX_CHECKS or retry later."
            )

        download_dir = Path("downloaded_files")
        download_dir.mkdir(parents=True, exist_ok=True)

        download_saved = False
        last_error = None
        for attempt in range(1, 4):
            try:
                human_wait(page, 1200, 2800)
                with page.expect_download(timeout=90000) as download_info:
                    download_action.wait_for(state="visible", timeout=20000)
                    download_action.scroll_into_view_if_needed()
                    download_action.click(timeout=10000)

                download = download_info.value
                target_path = download_dir / download.suggested_filename
                download.save_as(str(target_path))

                if target_path.exists() and target_path.stat().st_size > 0:
                    print(f"Downloaded report: {target_path.name} ({target_path.stat().st_size} bytes)")
                    download_saved = True
                    break

                last_error = f"Saved file is missing or empty: {target_path}"
            except Exception as exc:
                last_error = str(exc)

            cooldown_ms = random.randint(6000, 14000)
            print(f"Download attempt {attempt} failed. Retrying after {cooldown_ms/1000:.1f}s...")
            page.wait_for_timeout(cooldown_ms)

        if not download_saved:
            raise RuntimeError(f"Download could not be confirmed after retries. Last error: {last_error}")

        page.wait_for_timeout(2000)

    print("✅ bKash Automation Completed!")