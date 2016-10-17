#!/opt/vmware/bin/python
import argparse
import json
import os
import sys
import glob
import time
import logging
import platform
import subprocess
import shlex
import random
import traceback
import re
sys.path.append(os.environ['VMWARE_PYTHON_PATH'])
from cis.svcscfg import genDepTracker, isInstalledService, loadServicesFile
from cis.tools import processSvcDeps, getSvcName, svcPlatformName, initSvcsDepLogger
from appliance.installparamutil import InstallParameters
from cis.statusAggregator import StatusAggregator
from cis.progressReporter import ProgressReporter
from cis.defaults import (
   getFBStatusReportInternalFile, get_cis_rereg_dir, get_cis_tmp_dir,
   get_cis_config_dir, get_cloudvm_ram_size_bin, get_cis_log_dir,
   get_locale_dir, get_cis_data_dir
   )
from cis.utils import (
   create_dir, setupLogging, get_deployment_nodetype,
   get_db_type, run_command, invoke_command
   )
from cis.exceptions import composeFBIntErr, InvokeCommandException
from cis.baseCISException import BaseInstallException
from cis.l10n import localizedString, configure
from cis.msgL10n import MessageMetadata as _T
from cis.componentStatus import ComponentsExecutionStatusInfo
from cis.componentStatus import ProgressData
from cis.componentStatus import ErrorInfo
from cis.filelock import FileLock
from cis.json_utils import JsonSerializer
from cis.defaultStatusFunctor import SimpleComponentStatusReader
from cis.defaultStatusFunctor import SimpleComponentQuestionHandler
from cis.execution_settings import *
osIsLinux = platform.system() == 'Linux'
osIsWindows = platform.system() == 'Windows'
watchdogSubDirName = 'iiad'
watchdogMaintenanceModeName = 'iiad.maintenance-mode'
def isLinux():
   return osIsLinux
def isWindows():
   return osIsWindows
def getWatchdogSentinelFile():
   return os.path.join(get_cis_data_dir(), watchdogSubDirName,
                       watchdogMaintenanceModeName)
def removeWatchdogSentinelFile():
   name = getWatchdogSentinelFile()
   if os.path.isfile(name):
      os.remove(name)
actions = dict(firstboot="First boot", prefreeze="Pre-freeze",
               postthaw="Post-thaw")
actionNames = ", ".join(actions.keys())
fbSubActions = dict(firstboot="First boot", start="Start", stop="Stop",
                    uninstall="Uninstall")
fbSubActionNames = ", ".join(fbSubActions.keys())
parser = argparse.ArgumentParser()
parser.add_argument("--action", help="Action (%s)" % actionNames)
parser.add_argument("--subaction", help="Subaction for firstboot action (%s)" %
                    fbSubActionNames)
parser.add_argument("--stress", action="store_true",
                    help="Run firstboot with stress options on")
parser.add_argument("--maxDelay", default=4, type=int,
                    help="Maximum delay (secs) before launching firstboot scripts")
parser.add_argument("--logDirectory", default=None,
                    help="Override default log directory")
parser.add_argument("--statusFile", default=None,
                    help="Override default status file (must be absolute path)")
parser.add_argument("--fbWhiteList", default=None,
                    help="Comma-separated list of firstboot scriptnames to execute.")
parser.add_argument("--interactive", default=False, action='store_true',
                    help="Run in interactive mode")
parsedArgs = parser.parse_args()
stressOption = parsedArgs.stress
maxDelay = parsedArgs.maxDelay
logDir = parsedArgs.logDirectory
statusFile = parsedArgs.statusFile
fbWhiteList = parsedArgs.fbWhiteList.split(',') if parsedArgs.fbWhiteList else None
interactive = parsedArgs.interactive
if parsedArgs.action and parsedArgs.action not in actions:
    print "Unknown action ('%s')" % parsedArgs.action
    parser.print_help()
    sys.exit(1)
elif parsedArgs.action:
    action = parsedArgs.action
else:
    action = "firstboot"
subaction = parsedArgs.subaction
if action != "firstboot" and subaction:
    print "Subactions are only supported for firstboot action"
    parser.print_help()
    sys.exit(1)
elif action == "firstboot" and subaction and subaction not in fbSubActions:
    print "Unknown subaction ('%s')" % parsedArgs.subaction
    parser.print_help()
    sys.exit(1)
elif action == "firstboot" and not subaction:
    subaction = "firstboot"
# Create directories necessary for firstboots.
create_dir(get_cis_tmp_dir())
if logDir is None:
    logDir = os.path.join(os.environ['VMWARE_LOG_DIR'], action)
# Install param utility
installParams = InstallParameters()
#Configure locale specific logging file
configure(get_locale_dir(),
          installParams.getParameter('clientlocale', 'en')[1])
if not statusFile:
   statusFile = os.path.join(logDir, 'fbInstall.json')
else:
   assert(os.path.isabs(statusFile))
inFile = getFBStatusReportInternalFile()
try:
   os.remove(inFile)
except Exception:
   pass
# Ensure that files created during firstboot are readable by default
os.umask(022)
if isLinux():
   firstBootPathPrefix = '/usr/lib/'
   clearCommand = '/usr/bin/clear'
else:
   firstBootPathPrefix = os.path.join(os.environ['VMWARE_CIS_HOME'], action)
   clearCommand = None
# Set up file logging using CIS common lib util
setupLogging('%sInfrastructure' % action, logMechanism='file', logDir=logDir)
# Initialize service dependency injection logger.
initSvcsDepLogger()
if isLinux():
    svcPath = '/usr/lib/vmware-visl-integration/config/services.json'
else:
    svcPath = os.path.join(os.environ['VMWARE_CIS_HOME'],
                           'visl-integration', 'config',
                           'services.json')
svcConfig = {'svcs' : loadServicesFile(svcPath) }
# Persist information require post firstboot
if action == "firstboot" and subaction == 'firstboot':
   (source, svcConfig['deploymentType']) = \
      installParams.getParameter('deployment.node.type', 'embedded')
   # Write deployment node type install param value to a config file so as to
   # avoid reading install-params after deployment.
   # Note:- We should do this only on firstboot.
   deloymentTypeCfgPath = os.path.join(get_cis_config_dir(),
                                    'deployment.node.type')
   with open(deloymentTypeCfgPath, 'w') as fp:
      fp.write(svcConfig['deploymentType'])
   # If vSphere is configured with external DB, then embedded DB is not
   # installed. Hence persists this information to not start/stop
   # embedded DB in this case.
   # Note 'dbType' key in svcConfig dict must be same as in service-control
   (source, svcConfig['dbType']) = installParams.getParameter('db.type', 'embedded')
   # XXX: Should we assert here
   assert svcConfig['dbType'], "DB Type must be set"
   # If you change dbTypeCfgPath, please update cis.util.get_db_type()
   dbTypeCfgPath = os.path.join(get_cis_config_dir(), 'db.type')
   with open(dbTypeCfgPath, 'w') as fp:
      fp.write(svcConfig['dbType'])
else: # Uninstall
   # Read deployment.node.type from cfg file.
   svcConfig['deploymentType'] = get_deployment_nodetype()
   svcConfig['dbType'] = get_db_type()
# Deptracker currently requires below operation key to be set to decide
# whether to do reverse or same dependency ordering.
# XXX This key should go away once we better abstract Deptracker in svcscfg.py
if action == "firstboot" and subaction in ['uninstall', 'stop']:
   # Reverse dep ordering.
   svcConfig['operation'] = 'stop'
else:
   svcConfig['operation'] = 'start'
def isPythonExecutable(filename):
    if filename.endswith('.py'):
        return True
    else :
        try:
            with open(filename, "r") as fopen:
                firstLine = fopen.readline().rstrip()
                return firstLine.startswith('#!/usr/bin/python') or \
                        firstLine.startswith('#!/opt/vmware/bin/python')
        except IOError:
            return False
def lockDownCISDir():
   """
   Locks down parent of cis config directory. Only System and Administrators
   will get access to this directory. All subdirs are reset to inherit permissions
   from this parent directory.
   Based on PR 1335392, Update #20.
   """
   if not isWindows():
      return
   import win32api
   cmdPath = os.path.join(win32api.GetSystemDirectory(), 'icacls.exe')
   cisDirPath = os.path.dirname(get_cis_config_dir())
   adminGrpSid = '*S-1-5-32-544'
   systemSid = '*S-1-5-18'
   try:
      invoke_command([cmdPath, cisDirPath, '/grant:r', '%s:(OI)(CI)(F)' % systemSid,
                      '/grant:r', '%s:(OI)(CI)(F)' % adminGrpSid,
                      '/inheritance:r', '/L', '/Q'])
      invoke_command([cmdPath, os.path.join(cisDirPath, '*'), '/reset', '/T',
                      '/L', '/Q'])
      invoke_command([cmdPath, cisDirPath, '/setowner', adminGrpSid, '/T',
                      '/L', '/Q'])
   except InvokeCommandException as ex:
      err = _T('install.ciscommon.fbrun.cislockdown',
               'Failed to set permissions on %s')
      err_lmsg = localizedString(err, [cisDirPath])
      res = _T('install.ciscommon.fbrun.cislockdown.res',
               'Make sure that %s does not already exist and re-run the installer.')
      res_lmsg = localizedString(res, [cisDirPath])
      ex.appendErrorStack(err_lmsg)
      ex.getErrorInfo().resolution = res_lmsg
      raise
# helper function to parse the component stderr output and extract the
# exception information.
def parseErrorInfo(errfile):
   with open(errfile, "r") as fp:
      errlog = fp.read()
   errPattern = re.compile(r': ({.*^}$)', re.S | re.M)
   errMatch = re.search(errPattern, errlog)
   if not errMatch:
      logging.info("No localized error detail found in %s, assuming internal error" % errfile)
      return None
   errInfo = None
   try:
      errDict = json.loads(errMatch.group(1))
      # convert keys to ascii due to http://bugs.python.org/issue2646
      # this is fixed in 2.7
      errInfoArg =  dict(map(lambda (k, v): (str(k), v), errDict.items()))
      errInfo = ErrorInfo(**errInfoArg)
   except:
      logging.error("Failed to parse %s, assuming internal error" % errfile)
   return errInfo
class FailedSubProcess():
   '''
   nop class for bad executables
   '''
   def __init__(self):
      self.returncode = 1
      return
   def poll(self):
      return
   def wait(self):
      return
class FirstBootScript():
   def __init__(self, script, compName):
      self._proc = None
      script = script
      self._script = script
      self._compName = compName
      self._scriptName = os.path.splitext(os.path.basename(script))[0]
      self._logName = os.path.join(logDir, os.path.basename(script))
      self._openSSLTmpFile = os.path.join(logDir, self._scriptName + 'sslTmp.txt')
      self._errFileName = '%s_%d_stderr.log' % (self._logName, os.getpid())
      self._isDone = False
      self._skipped = False
   def run(self, arg):
      self._outFile = open('%s_%d_stdout.log' % (self._logName, os.getpid()), 'w')
      self._errFile = open(self._errFileName, 'w')
      close_fds = True if isLinux() else False
      self._isDone = False
      '''
        The shlex.split() function has a bug and does not handle
        unicode strings correctly, it just returns garbage.
        str() is added to convert to ascii
      '''
      if sys.executable != None and isPythonExecutable(self._script) :
         args = shlex.split(str('"%s" "%s"' %(sys.executable, self._script)))
      else :
         args = shlex.split(str('"%s"' % self._script))
      if arg:
          args.append('--action')
          args.append(arg)
          if self._compName != "vmafdd":
             args.append('--compkey')
             args.append(self._compName)
             args.append('--errlog')
             args.append(self._errFileName)
      logging.info('Running %s script: %s' % (action, args))
      try :
         import tempfile
         # Popen on windows requires ASCII characters
         env = {}
         for k in os.environ:
            env[k] = str(os.environ[k])
         env['RANDFILE'] = str(self._openSSLTmpFile)
         env['PYTHONPATH'] = str(os.environ['VMWARE_PYTHON_PATH'])
         self._proc = subprocess.Popen(args,
                                stdout=self._outFile,
                                stderr=self._errFile,
                                env=env, close_fds=close_fds)
      except OSError, ex:
         logging.critical('Failed to run %s' % arg...
