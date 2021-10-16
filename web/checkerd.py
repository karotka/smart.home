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
import importlib
import utils

def do(logFile):
    """
    This does the "work" of the daemon
    """
    logger = logging.getLogger('web')
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler('daemon_log')

    fh.setLevel(logging.INFO)

    formatstr = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(formatstr)

    fh.setFormatter(formatter)

    logger.addHandler(fh)

    while True:
        try:
            time.sleep(1)
            importlib.reload(checker)

            c = checker.Checker(logger)
            c.check()
        except Exception as e:
            logger.error(utils.fullExceptionInfo())




def startDaemon(pidf, logFile):
    """
    launches the daemon in its context
    """

    with daemon.DaemonContext(
            working_directory='.',
            umask=0o002,
            pidfile = pidfile.TimeoutPIDLockFile(pidf),
    ) as context: do(logFile)


if __name__ == "__main__":
    startDaemon(pidf = '/tmp/eg_daemon.pid', logFile = '/tmp/eg_daemon.log')
