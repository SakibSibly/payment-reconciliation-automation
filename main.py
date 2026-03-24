from nogod import run_nogod
from bkash import run_bkash
from billing_system import run_billing_system
from ssl_payment import run_ssl 

def main():
    print("🚀 Starting Automation...")
    run_billing_system()
    run_nogod()
    run_bkash()
    run_ssl()

    print("✅ All tasks completed!")

if __name__ == "__main__":
    main()