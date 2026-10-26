"""Install this checkout's user-local launcher without touching system files."""
import os
from pathlib import Path
import shlex
import sys

root=Path(__file__).resolve().parents[1]
bin_dir=Path.home()/'.local/bin'
apps=Path.home()/'.local/share/applications'
for directory in (bin_dir,apps): directory.mkdir(parents=True,exist_ok=True)
launcher=bin_dir/'obsbot-studio'
launcher.write_text('#!/bin/sh\nset -e\ncd '+shlex.quote(str(root))+'\nexec '+shlex.quote(sys.executable)+' -m obsbot_studio.ui "$@"\n')
launcher.chmod(0o755)
icon=root/'obsbot_studio/icon.svg'
entry=apps/'obsbot-studio.desktop'
entry.write_text('[Desktop Entry]\nType=Application\nName=OBSBOT Studio\nComment=Local Tiny 3 camera controls and preview\nExec="'+str(launcher)+'"\nIcon='+str(icon)+'\nTerminal=false\nCategories=AudioVideo;Video;\nStartupNotify=true\n')
print(f'Installed {launcher}\nInstalled {entry}')
