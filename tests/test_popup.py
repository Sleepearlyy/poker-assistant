import unittest

from popup import VK_A, VK_Q, game_title, hotkey_action, seat_label, price_text

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

if __name__=='__main__':unittest.main()
