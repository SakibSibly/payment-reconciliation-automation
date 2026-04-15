from nagad.billpay.nagad_244 import run_nagad_244
from nagad.billpay.nagad_744 import run_nagad_744
from nagad.pgw.nagad_066 import run_nagad_066
from nagad.pgw.nagad_377 import run_nagad_377
from nagad.pgw.nagad_742 import run_nagad_742

def run_nagad():
    run_nagad_244()
    run_nagad_744()
    run_nagad_066()
    run_nagad_377()
    run_nagad_742()

if __name__ == "__main__":
    run_nagad()