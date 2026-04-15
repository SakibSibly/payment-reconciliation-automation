from nagad.nagad import run_nagad
from bkash.pgw.bkash import run_bkash
from billing_system import run_billing_system
from ssl_payment import run_ssl
from utils.reconcile_upload import run_upload

def main():
    print("🚀 Starting Automation...")
    run_billing_system()
    run_nagad()
    run_bkash()
    run_ssl()

    print("🚀 Starting Upload and Comparison...")
    run_upload()

    print("✅ All tasks completed!")

if __name__ == "__main__":
    main()