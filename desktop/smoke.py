"""Exercise packaged Tk layouts without a network connection or user vault."""
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk


def check_ui(application):
    with tempfile.TemporaryDirectory(prefix='credlet ui smoke ') as temporary:
        previous=os.environ.get('CREDLET_CONFIG_DIR')
        os.environ['CREDLET_CONFIG_DIR']=temporary
        root=tk.Tk();app=None
        try:
            app=application(root);root.update()
            assert app.server.winfo_viewable() and app.unlock_button.winfo_viewable(), 'Sign-in form is not visible.'
            app.master.insert(0,'disposable-ui-fixture')
            app.render({'unlocked':True,'deadline':time.time()*1000+300000,'items':[
                {'id':'fixture','name':'Example login','username':'example','uris':[],'reprompt':0}]})
            for size in ('800x760','660x660'):
                root.geometry(size);root.update()
                for widget in (app.items,app.capture_button,app.fill_button,app.link_button):
                    assert widget.winfo_viewable(), 'A desktop action is hidden.'
                    bottom=widget.winfo_rooty()-root.winfo_rooty()+widget.winfo_height()
                    assert bottom<=root.winfo_height(), 'A desktop action extends below the window.'
            app.query.set('no-such-login');root.update()
            assert not app.items.get_children(), 'Search did not filter the vault.'
            app.query.set('');root.update()
            assert app.items.get_children(), 'Clearing search did not restore the vault.'
            app.render({'unlocked':False,'items':[]});root.update()
            assert not app.items.get_children() and not app.master.get(), 'Lock left vault contents in the UI.'
            assert not (Path(temporary)/'settings.json').exists(), 'Offline UI check persisted fixture state.'
        finally:
            if app:app.close()
            else:root.destroy()
            if previous is None:os.environ.pop('CREDLET_CONFIG_DIR',None)
            else:os.environ['CREDLET_CONFIG_DIR']=previous
