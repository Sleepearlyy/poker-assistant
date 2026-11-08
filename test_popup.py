"""End-to-end smoke test of the click-to-capture popup (Windows GUI).

The test never touches the real screen: it feeds a bundled screenshot through
the same hide -> read -> analyze -> render path and saves a picture of the
resulting window under results/popup-smoke.png.
"""
import sys
import time
import unittest

import cv2
import numpy as np

from reader import ROOT, enable_dpi
from popup import PokerPopup, VK_A, VK_Q, game_title, hotkey_action, seat_label, price_text

class Titles(unittest.TestCase):
    def test_poker_fate_title(self):
        self.assertTrue(game_title('Poker Fate'))
        self.assertTrue(game_title('PokerFate'))
        self.assertFalse(game_title('poker-screen-reader - Cursor'))

    def test_seat_label_uses_role(self):
        self.assertEqual(seat_label({'seat':'lower_left','presence':'occupied','role':'小盲'}),'小盲')
        self.assertEqual(seat_label({'seat':'bottom','presence':'occupied','role':'按钮'}),'按钮 · 自己')
        self.assertEqual(seat_label({'seat':'top','presence':'empty_or_unreadable','role':None}),'空位')

    def test_hotkey_a_scans_and_q_collapses(self):
        bare = dict(modifiers=False, typing=False, game_focused=True)
        self.assertEqual(hotkey_action(VK_A, panel_open=False, **bare), 'scan')
        self.assertEqual(hotkey_action(VK_A, panel_open=True, **bare), 'scan')
        self.assertEqual(hotkey_action(VK_Q, panel_open=True, **bare), 'collapse')
        self.assertIsNone(hotkey_action(VK_Q, panel_open=False, **bare))
        self.assertIsNone(hotkey_action(VK_A, modifiers=False, typing=True, game_focused=True, panel_open=True))
        self.assertIsNone(hotkey_action(VK_A, modifiers=True, typing=False, game_focused=True, panel_open=True))
        self.assertIsNone(hotkey_action(VK_Q, modifiers=False, typing=False, game_focused=False, panel_open=True))

    def test_price_text_names_all_in(self):
        self.assertEqual(price_text({'controls':{'source':'all_in_button','to_call':800}}),'全下 800')
        self.assertEqual(price_text({'controls':{'source':'check_button','to_call':0}}),'过牌')
        self.assertEqual(price_text({'controls':{'source':'call_button','to_call':1000}}),'跟注 1000')

@unittest.skipUnless(sys.platform=='win32' and (ROOT/'sample-spades.png').is_file(),'Windows GUI and private screenshot fixture required')
class Popup(unittest.TestCase):
    def test_click_to_result(self):
        import tkinter as tk
        enable_dpi()
        root=tk.Tk()
        app=PokerPopup(root,sample=str(ROOT/'sample-spades.png'),save_settings=False)
        try:
            app.scan()
            deadline=time.time()+90
            while time.time()<deadline and (app.busy or app.last_result is None):
                root.update()
                time.sleep(.05)
            root.update()
            self.assertFalse(app.busy,'popup did not finish')
            result=app.last_result
            self.assertIsNotNone(result)
            self.assertEqual(result['advice']['status'],'ok',result['advice'].get('message'))
            self.assertEqual(len(app.seats.get_children()),6)
            self.assertGreaterEqual(len(app.ev.get_children()),3)
            self.assertTrue(app.recommendation.get().startswith('建议 '))
            self.assertIn('胜率',app.equity.get())
            self.assertIn('对手',app.status.get())
            self.assertTrue(app.recommendation.get().strip())
            x,y=root.winfo_rootx(),root.winfo_rooty()
            w,h=root.winfo_width(),root.winfo_height()
            self.assertGreater(w,650);self.assertLess(h,360);self.assertGreater(w,h)
            with __import__('mss').mss() as capture:
                shot=np.asarray(capture.grab(dict(left=x,top=y,width=w,height=h)))[:,:,:3].copy()
            target=ROOT/'results'/'popup-smoke.png'
            target.parent.mkdir(parents=True,exist_ok=True)
            cv2.imencode('.png',shot)[1].tofile(str(target))
            self.assertTrue(app._hook)
            app._run_hotkey('collapse')
            root.update()
            self.assertFalse(app.expanded)
            self.assertLess(root.winfo_width(), 120)
        finally:
            root.destroy()

if __name__=='__main__':unittest.main()
