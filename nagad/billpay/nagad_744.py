import math
import json
import re
from pathlib import Path
import pandas as pd
from playwright.sync_api import Playwright, sync_playwright
from decouple import config
from datetime import datetime, timedelta


def run(playwright: Playwright) -> None:
    username = config("NAGAD_USER_01")
    password = config("NAGAD_PASS_01")
    login_url = config("NAGAD_URL")
    history_api_url = config(
        "NAGAD_HISTORY_API_URL",
        default="https://channel.mynagad.com:20010/api/biller-service/payment/history",
    )
    biller_service_no = config("NAGAD_BILLER_SERVICE_NO", default="1548")
    previous_days = config("PREVIOUS_DAYS", default=1, cast=int)
    page_size = 100
    target_dt = datetime.now() - timedelta(days=previous_days)
    target_date_api = target_dt.strftime("%Y%m%d")
    target_date_display = target_dt.strftime("%d-%m-%Y")
    target_day = str(target_dt.day)

    def extract_records(payload):
        if isinstance(payload, dict):
            for key in ["content", "data", "items", "records", "result"]:
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def parse_history_payload(response, page_no):
        if not response.ok:
            raise RuntimeError(
                f"Nagad history API failed on page {page_no}: "
                f"HTTP {response.status} | {response.text()[:500]}"
            )

        raw_text = (response.text() or "").strip()
        if not raw_text:
            # Some days may produce an empty body even with HTTP 200.
            return {"totalElements": 0, "content": []}

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            content_type = response.headers.get("content-type", "unknown")
            raise RuntimeError(
                f"Nagad history API returned non-JSON body on page {page_no}. "
                f"content-type={content_type} | body={raw_text[:500]}"
            )

    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(login_url)
    page.get_by_role("textbox", name="user name").click()
    page.get_by_role("textbox", name="user name").click()
    page.get_by_role("textbox", name="user name").fill(username)
    page.get_by_role("textbox", name="password").click()
    page.get_by_role("textbox", name="password").click()
    page.get_by_role("textbox", name="password").fill(password)
    page.get_by_role("button", name="Log In").click()
    page.get_by_role("link", name=" Payment ").click()
    page.get_by_role("link", name=" Bill Payment History").click()

    page.get_by_label("Service Name*").select_option(biller_service_no)
    page.locator(".input-group-text").first.click()
    page.get_by_text(target_day, exact=True).click()
    page.locator("div:nth-child(2) > .input-group > .input-group-append > .input-group-text > .fa").click()
    page.get_by_text(target_day, exact=True).click()

    with page.expect_response(re.compile(r".*/api/biller-service/payment/history.*"), timeout=30000) as first_history_response_info:
        page.get_by_role("button", name="Search", exact=True).click()

    first_history_response = first_history_response_info.value
    request_headers = first_history_response.request.all_headers()
    reusable_headers = {
        key: value
        for key, value in request_headers.items()
        if key.lower() not in {"content-length", "host"}
    }

    if not reusable_headers.get("authorization") and not reusable_headers.get("cookie"):
        raise RuntimeError(
            "Could not capture authentication context from Nagad history request "
            "(missing both authorization and cookie headers)."
        )

    base_params = {
        "pageSize": page_size,
        "billerServiceNo": biller_service_no,
        "approvalDateFrom": target_date_api,
        "approvalDateTo": target_date_api,
    }

    derived_history_api_url = first_history_response.url.split("?", 1)[0] or history_api_url
    first_response = context.request.get(
        derived_history_api_url,
        params={**base_params, "page": 1},
        headers=reusable_headers,
    )
    first_payload = parse_history_payload(first_response, 1)
    total_elements = int(first_payload.get("totalElements", 0)) if isinstance(first_payload, dict) else 0
    all_rows = extract_records(first_payload)

    total_pages = math.ceil(total_elements / page_size) if total_elements > 0 else 1

    for page_no in range(2, total_pages + 1):
        response = context.request.get(
            derived_history_api_url,
            params={**base_params, "page": page_no},
            headers=reusable_headers,
        )
        payload = parse_history_payload(response, page_no)
        all_rows.extend(extract_records(payload))

    output_dir = Path("downloaded_files") / "nagad"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"payment_history_744_{target_date_display}.xlsx"

    df = pd.json_normalize(all_rows) if all_rows else pd.DataFrame()

    if "approvalDatetime" in df.columns:
        approval_col = df["approvalDatetime"]
        numeric_approval = pd.to_numeric(approval_col, errors="coerce")

        # Nagad often returns epoch milliseconds; fall back to generic datetime parsing.
        parsed_approval_dt = pd.to_datetime(numeric_approval, unit="ms", errors="coerce")
        parsed_fallback = pd.to_datetime(approval_col, errors="coerce")
        parsed_approval_dt = parsed_approval_dt.fillna(parsed_fallback)

        formatted_approval = parsed_approval_dt.dt.strftime("%d-%m-%Y")
        df["approvalDatetime"] = formatted_approval.where(parsed_approval_dt.notna(), approval_col.astype(str))

    backend_message_cols = [
        col
        for col in df.columns
        if "message" in col.lower() and ("backend" in col.lower() or "download" in col.lower())
    ]
    if backend_message_cols:
        df = df.drop(columns=backend_message_cols)

    if not df.empty:
        backend_msg_pattern = r"backend.*download|download.*backend"
        row_has_backend_msg = df.astype(str).apply(
            lambda row: row.str.contains(backend_msg_pattern, case=False, regex=True, na=False).any(),
            axis=1,
        )
        df = df[~row_has_backend_msg].copy()

    df.to_excel(output_file, index=False)

    print(
        f"Saved Nagad payment history: {output_file} | "
        f"totalElements={total_elements} | fetched_rows={len(all_rows)} | pages={total_pages}"
    )

    # ---------------------
    context.close()
    browser.close()


def run_nagad_744():
    print("🚀 Starting Nagad 744 Automation...")
    with sync_playwright() as playwright:
        run(playwright)
    print("✅ Nagad 744 Automation Completed!")


def run_nagad():
    # Backward-compatible wrapper for existing imports (e.g., main.py).
    run_nagad_744()


if __name__ == "__main__":
    run_nagad_744()