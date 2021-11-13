import sys
import os
import time
import argparse
import daemon
from daemon import pidfile
import checker
from config import conf
import time
import logging
import logging.handlers
import importlib
import utils

def do():
    """
    This does the "work" of the daemon
    """
    logger = logging.getLogger('daemon_log')
    logger.setLevel(logging.INFO)
    fh = logging.handlers.TimedRotatingFileHandler(
         conf.Daemon.LogFile, when="midnight")

    fh.setLevel(logging.INFO)

    formatstr = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(formatstr)

    fh.setFormatter(formatter)

    logger.addHandler(fh)

    while True:
        try:
            importlib.reload(checker)

            c = checker.Checker(logger)
            c.check()
            time.sleep(1)
        except Exception as e:
            logger.error(sys.exc_info())


def startDaemon():
    """
    launches the daemon in its context
    """

    with daemon.DaemonContext(
            working_directory='.',
            umask=0o002,
            pidfile = pidfile.TimeoutPIDLockFile(conf.Daemon.Pid),
    ) as context: do()


if __name__ == "__main__":
    #startDaemon()
    do()
