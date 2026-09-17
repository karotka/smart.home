import sys
import os
import time
import argparse
import daemon
from daemon import pidfile
import checker
import alerts
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
    logger.setLevel(logging.DEBUG)

    logHandler = logging.handlers.TimedRotatingFileHandler(
         conf.Daemon.LogFile, when="midnight", backupCount = 4)
    formatter = logging.Formatter(
         '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)

    #print (logger)
    while True:
        try:
            importlib.reload(checker)

            c = checker.Checker(logger)
            c.check()
            #print ("loop")
        except Exception as e:
            logger.error(e, exc_info=True)

        # Alert evaluation — isolated so a failure here never blocks heating.
        # alerts.evaluate() is internally throttled (does real work every ~15 s).
        try:
            importlib.reload(alerts)
            alerts.evaluate(logger)
        except Exception as e:
            logger.error(e, exc_info=True)

        time.sleep(1)


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
