from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from seleniumbase import sb_cdp
from decouple import config
from datetime import date, timedelta
import random
import json
import re
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

            normalized_expected = expected_date_prefix.replace("-", "/")

            def normalize_cell_date(value):
                text = str(value).strip().splitlines()[0].strip()
                return text.replace("-", "/")

            normalized_dates = dates_as_text.apply(normalize_cell_date)
            out_of_scope = normalized_dates[~normalized_dates.str.startswith(normalized_expected, na=False)]
            if not out_of_scope.empty:
                log_debug(
                    f"Found {len(out_of_scope)} rows outside expected day '{normalized_expected}'. "
                    f"Example: {out_of_scope.iloc[0]}"
                )
            else:
                log_debug(f"All rows match expected day prefix: {normalized_expected}")
        except Exception as exc:
            log_debug(f"Failed to analyze downloaded report: {exc}")

    def human_wait(page, min_ms=700, max_ms=1800):
        page.wait_for_timeout(random.randint(min_ms, max_ms))

    def click_with_jitter(page, locator, label, retries=3, allow_scroll=True):
        for attempt in range(1, retries + 1):
            try:
                locator.first.wait_for(state="visible", timeout=20000)
                human_wait(page, 900, 2500)
                if allow_scroll:
                    needs_scroll = locator.first.evaluate(
                        """(el) => {
                            const rect = el.getBoundingClientRect();
                            const vh = window.innerHeight || document.documentElement.clientHeight;
                            return rect.top < 0 || rect.bottom > vh;
                        }"""
                    )
                    if needs_scroll:
                        locator.first.scroll_into_view_if_needed()
            except PlaywrightTimeoutError:
                if attempt == retries:
                    raise RuntimeError(f"{label} was not visible/clickable in time.")
                cooldown_ms = random.randint(3000, 9000)
                print(f"{label} not ready yet. Retrying in {cooldown_ms/1000:.1f}s...")
                page.wait_for_timeout(cooldown_ms)
                continue

            # 1) regular click; if it fails, immediately try force and JS fallbacks.
            click_succeeded = False
            try:
                locator.first.click(timeout=10000)
                click_succeeded = True
            except Exception:
                try:
                    # 2) force click
                    locator.first.click(timeout=10000, force=True)
                    click_succeeded = True
                except Exception:
                    # 3) JS-dispatched click events
                    try:
                        locator.first.evaluate(
                            """(el) => {
                                el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                                el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                            }"""
                        )
                        click_succeeded = True
                    except Exception:
                        click_succeeded = False

            if not click_succeeded:
                if attempt == retries:
                    raise RuntimeError(f"{label} click failed in all three modes.")
                cooldown_ms = random.randint(3000, 9000)
                print(f"{label} click failed. Retrying in {cooldown_ms/1000:.1f}s...")
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
        attach_api_diagnostics(page)

        date_format = config("DATE_FORMAT", default="%d/%m/%Y")
        yesterday = date.today() - timedelta(days=1)
        date_range_value = f"{yesterday.strftime(date_format)} - {yesterday.strftime(date_format)}"
        yesterday_iso = yesterday.strftime("%Y-%m-%d")
        expected_day_prefix = yesterday.strftime(date_format)

        current_wallet = {"value": ""}
        export_payload_rewritten = {"applied": False}

        def rewrite_download_details(route, request):
            if request.method == "POST" and "/api/v1/reports/download/details" in request.url:
                try:
                    payload = json.loads(request.post_data or "{}")
                    original_from = payload.get("dateFrom")
                    original_to = payload.get("dateTo")
                    original_wallet = payload.get("requesterWalletNumber")

                    payload["dateFrom"] = yesterday_iso
                    payload["dateTo"] = yesterday_iso
                    if current_wallet["value"]:
                        payload["requesterWalletNumber"] = current_wallet["value"]

                    export_payload_rewritten["applied"] = True
                    log_debug(
                        "Rewrote export payload: "
                        f"wallet {original_wallet}->{payload.get('requesterWalletNumber')}, "
                        f"date {original_from}..{original_to}->{payload['dateFrom']}..{payload['dateTo']}"
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

        def ensure_previous_days_selected():
            previous_days_btn = page.get_by_role("button", name="Previous Days", exact=True)
            today_btn = page.get_by_role("button", name="Today", exact=True)
            previous_days_btn.wait_for(state="visible", timeout=15000)

            def is_previous_days_selected() -> bool:
                previous_class = previous_days_btn.get_attribute("class") or ""
                today_class = today_btn.get_attribute("class") or ""
                previous_selected = "border-primary-500" in previous_class and "bg-primary-100" in previous_class
                today_deselected = "border-gray-300" in today_class and "bg-white" in today_class
                return previous_selected and today_deselected

            if not is_previous_days_selected():
                click_with_jitter(page, previous_days_btn, "Previous Days")

            if not is_previous_days_selected():
                previous_days_btn.evaluate(
                    """(el) => {
                        el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
                        el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                        el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                        el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    }"""
                )

        def collect_associated_wallets():
            wallets = []
            seen = set()

            for attempt in range(1, 4):
                page.goto("https://merchantportal.bkash.com/associated-wallets/list", wait_until="domcontentloaded")
                page.wait_for_timeout(1200)

                # Clear persisted filters so all associated wallets are visible.
                try:
                    wallet_filter = page.locator("input[placeholder='Wallet Number']").first
                    outlet_filter = page.locator("input[placeholder='Outlet/Business Name']").first
                    if wallet_filter.count() > 0:
                        wallet_filter.fill("")
                    if outlet_filter.count() > 0:
                        outlet_filter.fill("")
                except Exception as exc:
                    log_debug(f"Could not clear associated wallet filters on attempt {attempt}: {exc}")

                # Trigger search once to force table refresh when page opens empty.
                try:
                    search_btn = page.locator("button:has(span.material-icons:has-text('search'))").first
                    click_with_jitter(page, search_btn, "Associated Wallet Search", allow_scroll=False)
                except Exception as exc:
                    log_debug(f"Associated wallet search click skipped on attempt {attempt}: {exc}")

                page.wait_for_timeout(1500)
                # Collect wallets from current page and continue through pagination.
                max_pages = 20
                for _ in range(max_pages):
                    page.wait_for_selector("table.mr-table", timeout=15000)

                    wallet_cells = page.locator("table.mr-table tbody tr td:nth-child(2) div")
                    cell_count = wallet_cells.count()

                    for i in range(cell_count):
                        wallet = wallet_cells.nth(i).inner_text().strip()
                        if wallet.isdigit() and len(wallet) >= 11 and wallet not in seen:
                            wallets.append(wallet)
                            seen.add(wallet)

                    # Fallback: parse visible table text for wallet-like numbers.
                    try:
                        table_text = page.locator("table.mr-table").inner_text(timeout=5000)
                        for wallet in re.findall(r"\b01\d{9}\b", table_text):
                            if wallet not in seen:
                                wallets.append(wallet)
                                seen.add(wallet)
                    except Exception:
                        pass

                    next_btn = page.locator("button:has-text('Next')").first
                    if next_btn.count() == 0:
                        break

                    is_disabled = (next_btn.get_attribute("disabled") is not None) or (
                        (next_btn.get_attribute("aria-disabled") or "").lower() == "true"
                    )
                    if is_disabled:
                        break

                    click_with_jitter(page, next_btn, "Associated Wallet Next", allow_scroll=False)
                    page.wait_for_timeout(1200)

                if wallets:
                    print(f"Found {len(wallets)} associated wallets: {wallets}")
                    return wallets

                log_debug(f"No wallets found on attempt {attempt}; retrying...")
                page.wait_for_timeout(3000)

            print("Found 0 associated wallets: []")
            return wallets

        def apply_detailed_filters_for_wallet(wallet):
            page.goto("https://merchantportal.bkash.com/reports/detailed-reports", wait_until="domcontentloaded")
            page.wait_for_selector("input[name='displayDateRange']", timeout=30000)
            page.wait_for_selector("input[name='transactionId']", timeout=30000)
            ensure_previous_days_selected()

            date_range_input = page.locator("input[name='displayDateRange']")
            date_range_input.evaluate("el => el.removeAttribute('readonly')")
            date_range_input.fill(date_range_value)
            date_range_input.dispatch_event("input")
            date_range_input.dispatch_event("change")
            page.keyboard.press("Enter")

            wallet_input = page.locator("input[placeholder='Enter Associated Wallet']")
            wallet_input.wait_for(state="visible", timeout=15000)
            wallet_input.fill("")
            human_wait(page, 400, 900)
            wallet_input.fill(wallet)
            human_wait(page, 400, 900)
            page.keyboard.press("Enter")

            detailed_filter_grid = page.locator("div.grid").filter(has=page.locator("input[name='transactionId']")).first
            detailed_search_btn = detailed_filter_grid.locator("button:has(span.material-icons:has-text('search'))").first
            click_with_jitter(page, detailed_search_btn, f"Detailed Report Search ({wallet})", allow_scroll=False)
            print_recent_api_calls(f"After Detailed Report Search ({wallet})")

        def queue_and_download_for_wallet(wallet):
            export_payload_rewritten["applied"] = False

            download_btn = page.locator("div.card-header button:has-text('Download')").first
            click_with_jitter(page, download_btn, f"Download ({wallet})")

            excel_btn = page.locator("text=Download Excel").last
            click_with_jitter(page, excel_btn, f"Download Excel ({wallet})")
            print_recent_api_calls(f"After Download Excel click ({wallet})")

            if not export_payload_rewritten["applied"]:
                log_debug(f"Export payload rewrite hook did not trigger for wallet {wallet}.")

            track_status_btn = page.locator("button:has-text('Track Status')").first
            click_with_jitter(page, track_status_btn, f"Track Status ({wallet})")
            page.wait_for_url("**/reports/download-progress**", timeout=30000)

            status_ready = False
            download_action = page.locator(
                "table.mr-table tbody button:has-text('Download Report'), "
                "table.mr-table tbody span:has-text('Download Report'), "
                "table.mr-table tbody a:has-text('Download Report')"
            ).first

            for check in range(1, 4):
                page.reload(wait_until="domcontentloaded")
                human_wait(page, 1800, 4200)

                page.wait_for_selector("input[name='trackingId']", timeout=30000)
                progress_search_root = page.locator("div.grid").filter(has=page.locator("input[name='trackingId']")).first
                search_btn = progress_search_root.locator("button:has(span.material-icons:has-text('search'))").first
                click_with_jitter(page, search_btn, f"Download Progress Search ({wallet})", allow_scroll=False)

                try:
                    download_action.wait_for(state="visible", timeout=15000)
                    status_ready = True
                    break
                except PlaywrightTimeoutError:
                    if check < 3:
                        page.wait_for_timeout(5000)

            if not status_ready:
                raise RuntimeError(f"Download Report did not become available for wallet {wallet}.")

            download_dir = Path("downloaded_files") / "bkash"
            download_dir.mkdir(parents=True, exist_ok=True)

            with page.expect_download(timeout=90000) as download_info:
                download_action.scroll_into_view_if_needed()
                download_action.click(timeout=10000)

            download = download_info.value
            target_path = download_dir / f"{wallet}-{download.suggested_filename}"
            download.save_as(str(target_path))

            if not target_path.exists() or target_path.stat().st_size == 0:
                raise RuntimeError(f"Downloaded file missing/empty for wallet {wallet}: {target_path}")

            print(f"Downloaded report for {wallet}: {target_path.name} ({target_path.stat().st_size} bytes)")
            analyze_downloaded_report(target_path, expected_day_prefix)

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

        wallets = collect_associated_wallets()
        if not wallets:
            raise RuntimeError("No associated wallet numbers found on Associated Wallets page.")

        failed_wallets = []
        for wallet in wallets:
            print(f"Processing wallet: {wallet}")
            current_wallet["value"] = wallet
            try:
                apply_detailed_filters_for_wallet(wallet)
                queue_and_download_for_wallet(wallet)
            except Exception as exc:
                failed_wallets.append((wallet, str(exc)))
                print(f"Wallet {wallet} failed: {exc}")

        if failed_wallets:
            failed_text = "; ".join([f"{w}: {e}" for w, e in failed_wallets])
            raise RuntimeError(f"Some wallets failed to download: {failed_text}")

    print("✅ bKash Automation Completed!")


if __name__ == "__main__":
    run_bkash()