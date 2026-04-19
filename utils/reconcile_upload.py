from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from decouple import config
from playwright.sync_api import Playwright, TimeoutError as PlaywrightTimeoutError, expect, sync_playwright


CHANNEL_FILE_RE = re.compile(
    r"^(?P<wallet>\d{11})_(?P<kind>bkash_pgw|nagad_pgw|nagad_paybill)_(?P<date>\d{4}_\d{2}_\d{2})\.xlsx$",
    re.IGNORECASE,
)
BILLING_FILE_RE = re.compile(
    r"^(?P<system>mq|orbit_maxim|race_maxim)_payment_list_(?P<date>\d{4}_\d{2}_\d{2})\.xlsx$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ChannelUpload:
    channel_label: str
    wallet: str
    file_path: Path


@dataclass(frozen=True)
class BillingUpload:
    billing_system_label: str
    file_path: Path


def _parse_date_from_dir_name(data_dir: Path) -> date | None:
    match = re.search(r"(\d{4})_(\d{2})_(\d{2})", data_dir.name)
    if not match:
        return None
    year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return date(year, month, day)


def _resolve_target_date_and_dir(data_dir: str | Path | None) -> tuple[date, Path]:
    previous_days = config("PREVIOUS_DAYS", default=1, cast=int)
    derived_target = date.today() - timedelta(days=previous_days)
    derived_dir = Path(derived_target.strftime("%Y_%m_%d"))

    if data_dir is None:
        return derived_target, derived_dir

    chosen_dir = Path(data_dir)
    chosen_target = _parse_date_from_dir_name(chosen_dir) or derived_target
    return chosen_target, chosen_dir


def _discover_required_files(data_dir: Path, target_date_file: str) -> tuple[dict[tuple[str, str], Path], dict[str, Path]]:
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    channel_files: dict[tuple[str, str], Path] = {}
    billing_files: dict[str, Path] = {}

    for entry in data_dir.iterdir():
        if not entry.is_file() or entry.suffix.lower() != ".xlsx":
            continue

        channel_match = CHANNEL_FILE_RE.match(entry.name)
        if channel_match:
            if channel_match.group("date") != target_date_file:
                continue
            wallet = channel_match.group("wallet")
            kind = channel_match.group("kind").lower()
            channel_files[(kind, wallet)] = entry
            continue

        billing_match = BILLING_FILE_RE.match(entry.name)
        if billing_match:
            if billing_match.group("date") != target_date_file:
                continue
            system = billing_match.group("system").lower()
            billing_files[system] = entry

    return channel_files, billing_files


def _require(mapping: dict, key, hint: str) -> Path:
    if key not in mapping:
        present = ", ".join(str(k) for k in sorted(mapping.keys()))
        raise FileNotFoundError(f"Missing required file for {hint}. Present keys: {present or '<none>'}")
    return mapping[key]


def _portal_login(page, login_url: str, username: str, password: str) -> None:
    page.goto(login_url)
    page.get_by_role("textbox", name=re.compile(r"username", re.IGNORECASE)).click()
    page.get_by_role("textbox", name=re.compile(r"username", re.IGNORECASE)).fill(username)
    page.get_by_role("textbox", name=re.compile(r"password", re.IGNORECASE)).click()
    page.get_by_role("textbox", name=re.compile(r"password", re.IGNORECASE)).fill(password)
    page.get_by_role("button", name=re.compile(r"log\s*in", re.IGNORECASE)).click()
    page.wait_for_load_state("domcontentloaded")
    expect(page.get_by_role("button", name="Upload Files").first).to_be_visible(timeout=60000)


def _select_previous_date_first(page, target_date: date) -> None:
    # Keep the same general click flow as the reference codegen output,
    # but compute the day dynamically.
    page.locator(".MuiInputBase-root").first.click()

    # Best-effort month/year navigation when the target crosses months.
    try:
        header = page.locator(".MuiPickersCalendarHeader-label")
        prev_btn = page.get_by_label(re.compile(r"previous month", re.IGNORECASE))
        next_btn = page.get_by_label(re.compile(r"next month", re.IGNORECASE))

        def parse_header(text: str) -> date | None:
            cleaned = " ".join((text or "").split())
            try:
                dt = datetime.strptime(cleaned, "%B %Y")
                return date(dt.year, dt.month, 1)
            except Exception:
                return None

        for _ in range(24):
            label_text = header.first.inner_text(timeout=2000)
            shown_month = parse_header(label_text)
            if not shown_month:
                break

            target_month = date(target_date.year, target_date.month, 1)
            if shown_month == target_month:
                break

            if shown_month > target_month:
                prev_btn.click(timeout=2000)
            else:
                next_btn.click(timeout=2000)
    except Exception:
        # If the picker structure differs, continue with a simple day click.
        pass

    page.get_by_role("button", name=str(target_date.day), exact=True).click()
    page.get_by_role("button", name=re.compile(r"apply", re.IGNORECASE)).click()


def _select_dropdown_option(page, *, combobox_name: str, option_name: str) -> None:
    combo = page.get_by_role("combobox", name=re.compile(combobox_name, re.IGNORECASE))
    combo.click()
    page.get_by_role("option", name=option_name).click()
    # Close menus that sometimes stay open over the form.
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _select_channel(page, channel_label: str) -> None:
    _select_dropdown_option(page, combobox_name=r"select\s+channel", option_name=channel_label)


def _select_wallet(page, wallet: str) -> None:
    # Reference codegen had one initial wallet selection using a CSS locator;
    # prefer accessible name but fall back for older UI states.
    try:
        _select_dropdown_option(page, combobox_name=r"select\s+wallet", option_name=wallet)
        return
    except Exception:
        pass

    wallet_field = page.locator(
        ".MuiFormControl-root.MuiFormControl-fullWidth.MuiTextField-root"
    ).first
    wallet_field.click()
    page.get_by_role("option", name=wallet).click()
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _upload_file_via_button(page, file_path: Path, *, button_index: int) -> None:
    resolved_path = str(file_path.resolve())
    upload_button = page.get_by_role("button", name="Upload Files").nth(button_index)

    def try_set_on(locator) -> bool:
        try:
            locator.set_input_files(resolved_path)
            return True
        except Exception:
            return False

    # Some portals render this as a <label role="button"> with a hidden <input type=file>.
    # Playwright requires targeting the input element.
    if try_set_on(upload_button):
        page.wait_for_timeout(500)
        return

    nested_input = upload_button.locator("input[type='file']")
    if nested_input.count() > 0 and try_set_on(nested_input.first):
        page.wait_for_timeout(500)
        return

    # Last resort: pick the Nth file input on the page.
    file_inputs = page.locator("input[type='file']")
    if file_inputs.count() > button_index and try_set_on(file_inputs.nth(button_index)):
        page.wait_for_timeout(500)
        return

    raise RuntimeError(
        "Could not locate a usable <input type=file> for Upload Files. "
        "The portal UI structure may have changed."
    )


def upload_bkash(page, uploads: Iterable[ChannelUpload]) -> None:
    _select_channel(page, "Bkash PGW")
    for upload in uploads:
        _select_wallet(page, upload.wallet)
        _upload_file_via_button(page, upload.file_path, button_index=0)


def upload_nagad_paybill(page, uploads: Iterable[ChannelUpload]) -> None:
    _select_channel(page, "Nagad Paybill")
    for upload in uploads:
        _select_wallet(page, upload.wallet)
        _upload_file_via_button(page, upload.file_path, button_index=0)


def upload_nagad_pgw(page, uploads: Iterable[ChannelUpload]) -> None:
    _select_channel(page, "Nagad PGW")
    for upload in uploads:
        _select_wallet(page, upload.wallet)
        _upload_file_via_button(page, upload.file_path, button_index=0)


def upload_billing_system(page, uploads: Iterable[BillingUpload]) -> None:
    for upload in uploads:
        _select_dropdown_option(
            page,
            combobox_name=r"select\s+billing\s+system",
            option_name=upload.billing_system_label,
        )
        _upload_file_via_button(page, upload.file_path, button_index=1)


def compare_transactions(page) -> None:
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name=re.compile(r"compare\s+transactions", re.IGNORECASE)).click()


def run_upload(data_dir: str | Path | None = None, *, headless: bool | None = None) -> None:
    """Upload reconciliation files into the portal and trigger comparison.

    - Selects the previous date FIRST (derived from PREVIOUS_DAYS or the folder name).
    - Discovers required files from the target date directory using regex.
    - Uploads in the exact sequence of the provided reference script.

    Args:
        data_dir: Folder containing the *.xlsx files (defaults to YYYY_MM_DD for PREVIOUS_DAYS).
        headless: Override browser headless mode (defaults to RECONCILE_HEADLESS or False).
    """

    login_url = config("RECONCILE_URL")
    username = config("RECONCILE_USER")
    password = config("RECONCILE_PASS")
    if headless is None:
        headless = config("RECONCILE_HEADLESS", default=False, cast=bool)

    target_date, resolved_dir = _resolve_target_date_and_dir(data_dir)
    target_date_file = target_date.strftime("%Y_%m_%d")

    channel_files, billing_files = _discover_required_files(resolved_dir, target_date_file)

    # Upload order: match the codegen reference sequence.
    bkash_wallets = ["01322811782", "01332825960", "01844543183", "01988886328"]
    nagad_paybill_wallets = ["01322811759", "01332825960"]
    nagad_pgw_wallets = ["01322811782", "01322811758", "01332825961"]

    bkash_uploads = [
        ChannelUpload(
            channel_label="Bkash PGW",
            wallet=wallet,
            file_path=_require(
                channel_files,
                ("bkash_pgw", wallet),
                f"Bkash PGW wallet {wallet} ({target_date_file})",
            ),
        )
        for wallet in bkash_wallets
    ]
    nagad_paybill_uploads = [
        ChannelUpload(
            channel_label="Nagad Paybill",
            wallet=wallet,
            file_path=_require(
                channel_files,
                ("nagad_paybill", wallet),
                f"Nagad Paybill wallet {wallet} ({target_date_file})",
            ),
        )
        for wallet in nagad_paybill_wallets
    ]
    nagad_pgw_uploads = [
        ChannelUpload(
            channel_label="Nagad PGW",
            wallet=wallet,
            file_path=_require(
                channel_files,
                ("nagad_pgw", wallet),
                f"Nagad PGW wallet {wallet} ({target_date_file})",
            ),
        )
        for wallet in nagad_pgw_wallets
    ]

    billing_uploads = [
        BillingUpload(
            billing_system_label="MQ",
            file_path=_require(billing_files, "mq", f"Billing system MQ ({target_date_file})"),
        ),
        BillingUpload(
            billing_system_label="Orbit Maxim",
            file_path=_require(
                billing_files, "orbit_maxim", f"Billing system Orbit Maxim ({target_date_file})"
            ),
        ),
        BillingUpload(
            billing_system_label="Race Maxim",
            file_path=_require(
                billing_files, "race_maxim", f"Billing system Race Maxim ({target_date_file})"
            ),
        ),
    ]

    print(f"🚀 Starting Reconcile Upload (date={target_date_file}, dir={resolved_dir})...")

    with sync_playwright() as playwright:
        try:
            _run_portal_upload(
                playwright,
                login_url=login_url,
                username=username,
                password=password,
                headless=headless,
                target_date=target_date,
                bkash_uploads=bkash_uploads,
                nagad_paybill_uploads=nagad_paybill_uploads,
                nagad_pgw_uploads=nagad_pgw_uploads,
                billing_uploads=billing_uploads,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Timed out while uploading reconciliation files. "
                "The portal may be slow or selectors may need an update."
            ) from exc

    print("✅ Reconcile Upload Completed!")


def _run_portal_upload(
    playwright: Playwright,
    *,
    login_url: str,
    username: str,
    password: str,
    headless: bool,
    target_date: date,
    bkash_uploads: Iterable[ChannelUpload],
    nagad_paybill_uploads: Iterable[ChannelUpload],
    nagad_pgw_uploads: Iterable[ChannelUpload],
    billing_uploads: Iterable[BillingUpload],
) -> None:
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(60000)
    page.set_default_navigation_timeout(60000)

    _portal_login(page, login_url, username, password)

    # IMPORTANT: must select previous date first before any other dropdown.
    _select_previous_date_first(page, target_date)

    upload_bkash(page, bkash_uploads)
    upload_nagad_paybill(page, nagad_paybill_uploads)
    upload_nagad_pgw(page, nagad_pgw_uploads)
    upload_billing_system(page, billing_uploads)
    compare_transactions(page)

    context.close()
    browser.close()


if __name__ == "__main__":
    run_upload()