"""ADB UI helpers for the disposable Android acceptance emulator."""
import re
import subprocess
import xml.etree.ElementTree as ET


class AndroidUi:
    def __init__(self,adb,serial,port=5037):
        self.command=[str(adb),'-P',str(port),'-s',serial]

    def run(self,*arguments):
        return subprocess.run(self.command+list(arguments),check=True,capture_output=True,timeout=15).stdout

    def nodes(self):
        self.run('shell','uiautomator','dump','/sdcard/lockbox-acceptance-ui.xml')
        return list(ET.fromstring(self.run('exec-out','cat','/sdcard/lockbox-acceptance-ui.xml')).iter('node'))

    def tap(self,node):
        left,top,right,bottom=map(int,re.findall(r'\d+',node.get('bounds','')))
        self.run('shell','input','tap',str((left+right)//2),str((top+bottom)//2))

    def firefox_setup(self,package):
        """Complete first-run screens and dismiss the extension-install notification."""
        for _ in range(8):
            nodes=self.nodes();text='\n'.join(n.get('text','') for n in nodes)
            actions=[]
            if 'Set Firefox Nightly as your default browser app?' in text:actions=['CANCEL']
            elif 'Lockbox was added' in text:actions=['OK']
            elif 'Welcome to Firefox' in text:actions=['Continue']
            elif 'Open all your links with built-in privacy' in text:actions=['Not now']
            elif 'You’re protected' in text:actions=['Continue']
            if not actions:return
            target=next((n for n in nodes if n.get('text','').casefold() in {a.casefold() for a in actions}
                and n.get('package') in (package,'android','com.android.permissioncontroller','com.google.android.permissioncontroller')),None)
            if target is None:return
            self.tap(target)
        raise AssertionError('Firefox first-run UI did not finish.')
