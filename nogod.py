
import os
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime
from playwright.sync_api import Playwright, sync_playwright

load_dotenv()

username = os.getenv("NOGOD_USER")
password = os.getenv("NOGOD_PASS")


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(
        headless=False,
        args=["--start-maximized"]
    )

    context = browser.new_context(no_viewport=True)
    page = context.new_page()

    page.goto("https://auth.mynagad.com:10900/authentication-service-provider-1.0/login")

    page.get_by_role("textbox", name="user name").fill(username)
    page.get_by_role("textbox", name="password").fill(password)
    page.get_by_role("button", name="Log In").click()

    page.get_by_role("link", name=" Payment ").click()
    page.get_by_role("link", name=" Bill Payment History").click()

    page.get_by_label("Service Name*").select_option("1548")

    page.locator(".input-group-text").first.click()
    page.get_by_role("button", name="Previous month").click()
    page.get_by_label("Sunday, February 1,").get_by_text("1").click()

    page.locator("div:nth-child(2) > .input-group > .input-group-append > .input-group-text > .fa").click()
    page.get_by_role("button", name="Previous month").click()
    page.get_by_text("15", exact=True).click()

    page.get_by_label("Transaction Status").select_option("SUCCESS")

    page.get_by_role("button", name="Search", exact=True).click()

    with page.expect_response(
        lambda response: "payment/history" in response.url and response.status == 200
    ) as response_info:
        page.get_by_role("button", name="100").click()

    response = response_info.value
    data = response.json()
    records = data["content"]

    for item in records:
        item["approvalDatetime"] = datetime.fromtimestamp(
            item["approvalDatetime"] / 1000
        ).strftime("%Y-%m-%d %H:%M:%S")

    df = pd.DataFrame(records)
    df.to_excel("bill_payment_history.xlsx", index=False)

    print("✅ Nogod Excel Exported Successfully!")

    page.locator("#dropdownBasic3").click()
    page.locator("a").filter(has_text="Logout").click()

    context.close()
    browser.close()


# 👉 ONLY run when direct call
def run_nogod():
    with sync_playwright() as playwright:
        run(playwright)