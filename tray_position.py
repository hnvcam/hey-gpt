"""Find the configured status panel's output instead of assuming primary means panel."""
import os
from pathlib import Path
import re


def panel_output(config_home=None):
    root=Path(config_home or os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'cosmic'
    for folder in sorted(root.glob('com.system76.CosmicPanel.*/v1')):
        try:
            plugins=' '.join((folder/name).read_text() if (folder/name).exists() else ''
                             for name in ('plugins_wings','plugins_center'))
            if 'com.system76.CosmicAppletStatusArea' not in plugins:continue
            output=(folder/'output').read_text().strip()
            match=re.fullmatch(r'Name\("([^"\n]+)"\)',output)
            return match.group(1) if match else None
        except OSError:continue
    return None


def choose_monitor(monitors, output):
    if output:
        match=next((m for m in monitors if m['name']==output),None)
        if match:return match,'status-panel-output'
    return (next((m for m in monitors if m['primary']),monitors[0]),'primary-fallback') if monitors else (None,'no-monitors')


def board_position(area, width, height, margin=12, panel_height=36):
    x,y,w,h=area
    return max(x+margin,x+w-width-margin),max(y+margin,min(y+panel_height+margin,y+h-height-margin))
