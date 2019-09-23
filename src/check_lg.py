import os

from gzero.littlegolem import LittleGolemConnection


def check_lg():
    wd = os.getcwd()
    try:
        os.chdir("/home/rxe/working/gzero_sandbox/src/gzero")
        lg = LittleGolemConnection("lg_gzero.conf")
        waits = list(lg.games_waiting())
        return len(waits) > 0

    finally:
        os.chdir(wd)


if __name__ == "__main__":
    print check_lg()
