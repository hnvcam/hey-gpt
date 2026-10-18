"""Simulated monitor and panel configuration; no live desktop control."""
from pathlib import Path
import tempfile
import unittest
from tray_position import panel_output, choose_monitor, board_position


class Placement(unittest.TestCase):
    def test_status_panel_on_non_primary_display_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'cosmic'
            dock=root/'com.system76.CosmicPanel.Dock/v1';dock.mkdir(parents=True)
            panel=root/'com.system76.CosmicPanel.Panel/v1';panel.mkdir(parents=True)
            for folder in (dock,panel):
                (folder/'plugins_center').write_text('Some([])')
            (dock/'plugins_wings').write_text('Some(([], []))')
            (dock/'output').write_text('Name("HDMI-A-1")')
            (panel/'plugins_wings').write_text('Some((["com.system76.CosmicAppletStatusArea"], []))')
            (panel/'output').write_text('Name("DP-1")')
            output=panel_output(directory)
        monitors=[{'name':'HDMI-A-1','primary':True,'area':(1920,0,1080,1920)},
                  {'name':'DP-1','primary':False,'area':(0,0,1920,1080)}]
        chosen,reason=choose_monitor(monitors,output)
        self.assertEqual(chosen['name'],'DP-1')
        self.assertEqual(reason,'status-panel-output')
        x,y=board_position(chosen['area'],440,260)
        self.assertTrue(0<=x<x+440<=1920)
        self.assertTrue(0<=y<y+260<=1080)

    def test_missing_output_falls_back_and_position_handles_negative_coordinates(self):
        monitors=[{'name':'DP-2','primary':True,'area':(-1920,-100,1920,1080)}]
        chosen,reason=choose_monitor(monitors,'disconnected')
        self.assertEqual(reason,'primary-fallback')
        x,y=board_position(chosen['area'],440,300)
        self.assertTrue(-1920<=x<x+440<=0)
        self.assertTrue(-100<=y<y+300<=980)
        self.assertEqual(choose_monitor([],None),(None,'no-monitors'))
