#
# Copyright (c) 2013 Citrix Systems, Inc.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

"""Turn a VM into a PVM"""
from bvtlib.run import run
from bvtlib.time_limit import time_limit
from bvtlib.wait_for_windows import wait_for_windows, is_windows_up
from bvtlib.start_vm import start_vm_if_not_running
from bvtlib.call_exec_daemon import run_via_exec_daemon, call_exec_daemon
from bvtlib.exceptions import ExternalFailure
from time import sleep
from bvtlib.retry import retry
from bvtlib.mongodb import get_autotest
from bvtlib.settings import PVM_PLATFORMS
from bvtlib.install_tools_windows import tools_install_problems

CHANGE_THEME_VBS = '''
Set WshShell = WScript.CreateObject("WScript.Shell")

WshShell.Run "rundll32.exe %SystemRoot%\system32\shell32.dll,Control_RunDLL %SystemRoot%\system32\desk.cpl desk,@Themes /Action:OpenTheme /file:""C:\Windows\Resources\Themes\landscapes.theme"""

Wscript.Sleep 10000
WshShell.AppActivate("Desktop Properties")
WshShell.Sendkeys "%FC"
WshShell.Sendkeys "%{F4}"
'''

class UnableToEnablePVM(ExternalFailure): 
    """Unable to enable PVM"""

def have_accelerated_graphics( dut, domain, vm_address=None, timeout=10):
    """Test if domain on dut is a PVM"""
    if vm_address is None:
        vm_address = wait_for_windows(dut, domain, timeout=timeout)
    retry(lambda:call_exec_daemon(
            'unpackTarball',
            ['http://autotest.cam.xci-test.com/bin/devcon.tar.gz',
             'C:\\'], host=vm_address, timeout=timeout), 
          timeout=600, description='download devcon')
    displays = run_via_exec_daemon(
        ['C:\\devcon\\i386\\devcon.exe listclass Display'], host=vm_address,
        timeout=timeout)
    print 'INFO: accelerated graphics output', repr(displays)
    return ('VEN_1234' not in displays) and \
        ('Standard VGA Graphics' not in displays) and \
        ('No devices' not in displays)

def test_graphics(vm_address, dut, domain):
    """Set 3D theme so we know pass through is working"""
    # TODO: check windows version properly
    if 'win7' not in domain:  
        return
    call_exec_daemon('createFile', ['C:\\set_theme.vbs', CHANGE_THEME_VBS], 
                     host=vm_address)
    run_via_exec_daemon(['C:\\set_theme.vbs'], host=vm_address)

def accelerate_graphics(dut, domain):
    """Turn domain into a PVM"""
    print 'HEADLINE: ensuring acceleration enabled to', dut, domain
    start_vm_if_not_running(dut, domain)
    vm_address = wait_for_windows(dut, domain)
    if have_accelerated_graphics(dut, domain, vm_address):
        print 'HEADLINE: already have accelerated graphics on', dut, domain
        test_graphics(vm_address, dut, domain)
        return
    print 'HEADLINE: no accelerated graphics on', dut, domain, \
        'so will enable acceleration'
    with time_limit(3600, 'enable PVM on '+domain+' on '+dut):
        vm_address = wait_for_windows(dut, domain)
        run(['xec-vm', '-n', domain, 'set', 'pv-addons', 'true'], timeout=600, 
            host=dut)
        run(['xec-vm', '-n', domain, 'shutdown'], timeout=600, host=dut)
        while is_windows_up(vm_address):
            print 'INFO: windows still up'
            sleep(1)
        run(['xec-vm', '-n', domain, 'set', 'gpu', 'hdx'], timeout=600, 
            host=dut)
        run(['xec-vm', '-n', domain, 'start'], timeout=600, host=dut)
        with time_limit(1200, 'wait for windows driver model'):
            while 1:
                uuid_ex = run(['xec-vm', '-n', domain, 'get', 'uuid'], host=dut)
                uuid = uuid_ex.split()[0]
                print 'INFO:', 'uuid', uuid 
                out = run(['xenvm-cmd', uuid, 'pci-list'], host=dut)
                print 'PCI pass through status:'
                print out
                ready = have_accelerated_graphics(dut, domain, vm_address)
                print 'HEADLINE','accelerated graphics installed' if \
                  ready else  'accelerated graphics not ready'
                if ready:
                    break
                sleep(10)
    test_graphics(vm_address, dut, domain)

def futile(dut, guest, os_name, build, domlist):
    """Would it be futile to accelerate graphics?"""
    if not (os_name.startswith('win') or os_name=='xp'):
        return os_name+' is not supported for accelerate graphics (has to start "win")'
    mdb = get_autotest()
    dut_doc = mdb.duts.find_one({'name': dut})
    supported = dut_doc.get('platform') in PVM_PLATFORMS
    print 'ACCELERATE_GRAPHICS:', dut_doc.get('platform'), 'is', \
        'SUPPORTED' if supported else 'UNSUPPORTED', 'for PVMs'
    if not supported:
        return 'platform %r not supported (only %r supported)' % (
            dut_doc.get('platform'), PVM_PLATFORMS)
    for dom in domlist:
        print 'ACCELERATE_GRAPHICS: consider domain', dom
        if tools_install_problems(dut, dom['name']):
            return 'tools install problems in '+dom['name']
        try:
            if have_accelerated_graphics(dut, dom['name'], timeout=5):
                return dom['name'] + " already has accelerated graphics"
        except Exception, exc:
            print 'ACCELERATE_GRAPHICS: Unable to determine accelerated graphics state on', dom

TEST_CASES = [{
        'description': 'Accelerate graphics for $(OS_NAME)', 'bvt':True,
        'command_line_options' : ['-a', '--accelerate-graphics'], 
        'trigger' : 'VM accelerate', 'futile' : futile,
        'function': accelerate_graphics,
        'arguments': [('dut', '$(DUT)'), ('domain', '$(GUEST)')]}]

