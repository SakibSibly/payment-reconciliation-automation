from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from seleniumbase import sb_cdp
from decouple import config
from datetime import date, timedelta
import random
import json
from pathlib import Path
import pandas as pd

def run_bkash():
    print("🚀 Starting bKash Automation...")
    debug_enabled = config("BKASH_DEBUG", default=True, cast=bool)
    api_calls = []

    def log_debug(message):
        if debug_enabled:
            print(f"[BKASH_DEBUG] {message}")

    def attach_api_diagnostics(page):
        def on_request(request):
            url_lower = request.url.lower()
            if not any(key in url_lower for key in ["report", "download", "detailed", "track", "search"]):
                return

            if request.method not in {"GET", "POST", "PUT", "PATCH"}:
                return

            post_data = request.post_data or ""
            api_calls.append(
                {
                    "method": request.method,
                    "url": request.url,
                    "post_data": post_data,
                }
            )

            if len(api_calls) > 60:
                del api_calls[0]

        page.on("request", on_request)

    def print_recent_api_calls(tag, count=6):
        if not debug_enabled:
            return

        print(f"[BKASH_DEBUG] --- {tag}: recent API calls ---")
        for idx, call in enumerate(api_calls[-count:], start=1):
            post_data = (call.get("post_data") or "").strip()
            if len(post_data) > 500:
                post_data = post_data[:500] + "..."
            print(
                f"[BKASH_DEBUG] {idx}. {call['method']} {call['url']}\n"
                f"[BKASH_DEBUG]    payload: {post_data if post_data else '<empty>'}"
            )

    def analyze_downloaded_report(file_path, expected_date_prefix):
        if not debug_enabled:
            return

        try:
            raw_df = pd.read_excel(file_path, header=None)
            header_row_idx = None
            header_keywords = {"date time", "date", "datetime", "transaction id", "transaction type"}

            max_scan_rows = min(40, len(raw_df.index))
            for idx in range(max_scan_rows):
                row_values = [str(v).strip().lower() for v in raw_df.iloc[idx].tolist() if str(v).strip() and str(v).strip().lower() != "nan"]
                if not row_values:
                    continue

                overlap = sum(1 for v in row_values if v in header_keywords)
                if overlap >= 2 or any(v in {"date time", "datetime"} for v in row_values):
                    header_row_idx = idx
                    break

            if header_row_idx is None:
                log_debug("Could not detect header row in downloaded report.")
                return

            header_values = [str(v).strip() for v in raw_df.iloc[header_row_idx].tolist()]
            df = raw_df.iloc[header_row_idx + 1 :].copy()
            df.columns = header_values
            df = df.dropna(how="all")

            if df.empty:
                log_debug("Downloaded report is empty.")
                return

            date_col = None
            for col in df.columns:
                if str(col).strip().lower() in {"date time", "date", "datetime"}:
                    date_col = col
                    break

            if date_col is None:
                log_debug(f"Could not find Date Time column. Columns: {list(df.columns)}")
                return

            dates_as_text = df[date_col].astype(str).str.strip()
            sample_head = dates_as_text.head(5).tolist()
            sample_tail = dates_as_text.tail(5).tolist()
            min_seen = dates_as_text.min()
            max_seen = dates_as_text.max()

            log_debug(f"Date column detected: {date_col}")
            log_debug(f"First 5 rows: {sample_head}")
            log_debug(f"Last 5 rows: {sample_tail}")
            log_debug(f"Min/Max textual date values: {min_seen} | {max_seen}")

            out_of_scope = dates_as_text[~dates_as_text.str.startswith(expected_date_prefix, na=False)]
            if not out_of_scope.empty:
                log_debug(
                    f"Found {len(out_of_scope)} rows outside expected day '{expected_date_prefix}'. "
                    f"Example: {out_of_scope.iloc[0]}"
                )
            else:
                log_debug(f"All rows match expected day prefix: {expected_date_prefix}")
        except Exception as exc:
            log_debug(f"Failed to analyze downloaded report: {exc}")

    def human_wait(page, min_ms=700, max_ms=1800):
        page.wait_for_timeout(random.randint(min_ms, max_ms))

    def click_with_jitter(page, locator, label, retries=3):
        for attempt in range(1, retries + 1):
            try:
                locator.first.wait_for(state="visible", timeout=20000)
                human_wait(page, 900, 2500)
                locator.first.scroll_into_view_if_needed()

                # 1) regular click
                locator.first.click(timeout=10000)
            except PlaywrightTimeoutError:
                if attempt == retries:
                    raise RuntimeError(f"{label} was not visible/clickable in time.")
                cooldown_ms = random.randint(3000, 9000)
                print(f"{label} not ready yet. Retrying in {cooldown_ms/1000:.1f}s...")
                page.wait_for_timeout(cooldown_ms)
                continue
            except Exception:
                # 2) force click
                try:
                    locator.first.click(timeout=10000, force=True)
                except Exception:
                    # 3) JS-dispatched click events
                    locator.first.evaluate(
                        """(el) => {
                            el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                            el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                            el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                            el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                        }"""
                    )

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
        attach_api_diagnostics(page)
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
        yesterday_iso = yesterday.strftime("%Y-%m-%d")

        date_range_input = page.locator('input[name="displayDateRange"]')
        date_range_input.wait_for(state="visible", timeout=15000)
        date_range_input.evaluate("el => el.removeAttribute('readonly')")
        date_range_input.fill(date_range_value)
        date_range_input.dispatch_event("input")
        date_range_input.dispatch_event("change")
        page.keyboard.press("Enter")

        # Apply the filter explicitly; without this, export can include unfiltered history.
        detailed_action_container = page.locator("div.flex.items-center.space-x-2").first
        detailed_search_btn = detailed_action_container.locator("button").first
        click_with_jitter(page, detailed_search_btn, "Detailed Report Search")
        print_recent_api_calls("After Detailed Report Search")

        expected_day_prefix = yesterday.strftime(date_format)
        try:
            page.wait_for_function(
                """(expectedDay) => {
                    const rows = [...document.querySelectorAll('table.mr-table tbody tr')];
                    if (rows.length === 0) return true;

                    const firstCell = rows[0].querySelector('td');
                    const firstDateText = (firstCell?.textContent || '').trim();
                    return firstDateText.startsWith(expectedDay);
                }""",
                arg=expected_day_prefix,
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            first_row_text = page.locator("table.mr-table tbody tr td").first.inner_text(timeout=5000)
            raise RuntimeError(
                "Detailed report filter was not applied to yesterday-only data. "
                f"Expected first row starting with '{expected_day_prefix}', got '{first_row_text}'."
            )

        # Use text/CSS fallback because strict role+exact name can fail in Quasar dropdown buttons.
        download_btn = page.locator("div.card-header button:has-text('Download')").first
        click_with_jitter(page, download_btn, "Download")
        print_recent_api_calls("After Download button")

        # bKash keeps a separate internal export state; enforce yesterday-only at request level.
        export_payload_rewritten = {"applied": False}

        def rewrite_download_details(route, request):
            if request.method == "POST" and "/api/v1/reports/download/details" in request.url:
                try:
                    payload = json.loads(request.post_data or "{}")
                    original_from = payload.get("dateFrom")
                    original_to = payload.get("dateTo")
                    payload["dateFrom"] = yesterday_iso
                    payload["dateTo"] = yesterday_iso
                    export_payload_rewritten["applied"] = True
                    log_debug(
                        "Rewrote export payload date range: "
                        f"{original_from}..{original_to} -> {payload['dateFrom']}..{payload['dateTo']}"
                    )
                    route.continue_(
                        headers={**request.headers, "content-type": "application/json"},
                        post_data=json.dumps(payload),
                    )
                    return
                except Exception as exc:
                    log_debug(f"Failed to rewrite export payload: {exc}")

            route.continue_()

        page.route("**/api/v1/reports/download/details", rewrite_download_details)

        excel_btn = page.locator("text=Download Excel").last
        click_with_jitter(page, excel_btn, "Download Excel")
        print_recent_api_calls("After Download Excel click")

        if not export_payload_rewritten["applied"]:
            log_debug("Export payload rewrite hook did not trigger.")

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
            print_recent_api_calls(f"After Download Progress Search #{check}")

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
                    analyze_downloaded_report(target_path, yesterday.strftime(date_format))
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