import copy
import unittest
import cv2
import numpy as np
from advisor import call_engine,analyze,get_context
from reader import Reader,load_image,trim_titlebar,load_layout,roi,ROOT

class AdvisorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all((ROOT/name).is_file() for name in ('sample-spades.png','sample-turn.png')):
            raise unittest.SkipTest('Private screenshot fixtures are not distributed')
        frame=trim_titlebar(load_image(ROOT/'sample-spades.png'))
        _,layout=load_layout(ROOT/'layouts.json',frame,'auto')
        cls.reader=Reader(layout)
        cls.snapshot=cls.reader.scan(frame)
        turn=trim_titlebar(load_image(ROOT/'sample-turn.png'))
        _,turn_layout=load_layout(ROOT/'layouts.json',turn,'auto')
        cls.turn_snapshot=Reader(turn_layout).scan(turn)

    def test_spades_and_price(self):
        r=self.snapshot
        self.assertEqual([c['card'] for c in r['hero_cards']],['J♦','Q♠'])
        self.assertEqual([c['card'] for c in r['board_cards']][:3],['A♥','K♦','10♦'])
        self.assertEqual(r['pot']['value'],18000)
        self.assertEqual(r['controls']['to_call'],0)
        self.assertEqual(r['dealer']['seat'],'lower_right')
        dealer=next(s for s in r['seats'] if s['seat']=='lower_right')
        self.assertEqual(dealer['role'],'按钮')
        self.assertNotIn('左', ''.join(s.get('role') or '' for s in r['seats']))

    def test_jack_on_spade_grey(self):
        frame=trim_titlebar(load_image(ROOT/'sample-spades.png'))
        _,layout=load_layout(ROOT/'layouts.json',frame,'auto')
        jack=roi(frame, layout['hero_cards'][0]).copy()
        queen=roi(frame, layout['hero_cards'][1])
        hsv=cv2.cvtColor(jack, cv2.COLOR_BGR2HSV)
        h,s,v=cv2.split(hsv)
        blue=(h>92)&(h<130)&(s>70)&(v>110)
        qhsv=cv2.cvtColor(queen, cv2.COLOR_BGR2HSV)
        grey=queen[(qhsv[:,:,1]<55)&(qhsv[:,:,2]>25)&(qhsv[:,:,2]<170)]
        jack[blue]=np.median(grey, axis=0)
        painted=frame.copy()
        y1,x1=int(layout['hero_cards'][0][1]*frame.shape[0]), int(layout['hero_cards'][0][0]*frame.shape[1])
        painted[y1:y1+jack.shape[0], x1:x1+jack.shape[1]]=jack
        card=self.reader.card(painted, layout['hero_cards'][0], 'grey_jack')
        self.assertEqual(card['card'],'J♠')

    def test_panel_prices_are_not_pot_or_player_bets(self):
        r=self.reader.scan(trim_titlebar(load_image(ROOT/'sample-turn.png')))
        self.assertEqual(r['pot']['value'],90000)
        self.assertEqual(r['controls']['to_call'],0)
        self.assertEqual(r['bet_presets'],[30000,45000,60000,90000])
        self.assertEqual(r['seats'][1]['action'],'fold')
        self.assertIsNone(r['seats'][2]['stack'])
        self.assertEqual(r['board_cards'][3]['card'],'6♣')

    def test_missing_hero_and_duplicate_cards_block(self):
        r=copy.deepcopy(self.snapshot);r['seats'][3]['action']='fold'
        self.assertEqual(analyze(r)['status'],'insufficient_data')
        r=copy.deepcopy(self.snapshot);r['hero_cards'][0]=r['board_cards'][0]
        self.assertEqual(analyze(r)['status'],'insufficient_data')

    def test_price_from_visible_bets_without_button_amount(self):
        # This client's call button says only "跟注". Hero is the small blind
        # (500 in), a raise to 2500 is visible: price must come out as 2000.
        r=copy.deepcopy(self.snapshot)
        r['controls']={'to_call':None,'source':None,'hero_turn':True}
        for seat in r['seats']:seat['displayed_bet']=None
        r['seats'][3]['displayed_bet']={'value':500,'display':'500','approximate':False}    # bottom/hero, SB
        r['seats'][4]['displayed_bet']={'value':1000,'display':'1000','approximate':False}  # BB
        r['seats'][5]['displayed_bet']={'value':2500,'display':'2500','approximate':False}  # raise
        c=get_context(r)
        self.assertEqual(c['call'],2000)
        self.assertEqual(c['price_source'],'visible_bet_difference_estimate')

    def test_preflop_uses_visible_bets_as_pot(self):
        r=copy.deepcopy(self.snapshot)
        r['pot']=None
        for card in r['board_cards']:
            card.update(card=None,rank=None,suit=None,status='unknown')
        for seat in r['seats']:
            seat['displayed_bet']=None
        r['seats'][4]['displayed_bet']={'value':500,'display':'500','approximate':False}
        r['seats'][5]['displayed_bet']={'value':1000,'display':'1000','approximate':False}
        r['controls']={'to_call':None,'source':None,'hero_turn':True}
        c=get_context(r)
        self.assertEqual(c['board'],[])
        self.assertEqual(c['pot'],1500)
        self.assertEqual(c['call'],1000)
        self.assertTrue(any('翻前' in x for x in c['assumptions']))
        r['pot']=None
        r['seats'][4]['displayed_bet']=None
        c=get_context(r)
        self.assertEqual(c['pot'],1000)
        self.assertEqual(c['call'],1000)

    def test_call_bigger_than_center_pot_still_gets_advice(self):
        r=copy.deepcopy(self.snapshot)
        r['pot']={'value':1000,'display':'1000','approximate':False}
        r['controls']={'to_call':2500,'source':'call_button','hero_turn':True}
        for seat in r['seats']:
            seat['displayed_bet']=None
        r['seats'][5]['displayed_bet']={'value':2500,'display':'2500','approximate':False}
        c=get_context(r)
        self.assertEqual(c['call'],2500)
        self.assertEqual(c['pot'],3500)
        self.assertTrue(any('面前的下注' in x for x in c['assumptions']))

    def test_all_in_button_calls_the_whole_stack(self):
        r=copy.deepcopy(self.snapshot)
        hero=next(s for s in r['seats'] if s['seat']=='bottom')
        hero['stack']={'value':800,'display':'800','approximate':False}
        hero['displayed_bet']=None
        for seat in r['seats']:
            if seat is not hero:seat['displayed_bet']=None
        r['pot']={'value':5000,'display':'5000','approximate':False}
        r['controls']={'to_call':None,'source':'all_in_button','hero_turn':True}
        c=get_context(r)
        self.assertEqual(c['call'],800)
        self.assertTrue(c['shove_or_fold'])
        advice=analyze(r)
        self.assertEqual(advice['status'],'ok')
        self.assertEqual([a['action'] for a in advice['actions']],['fold','all_in'])
        self.assertEqual(advice['actions'][1]['amount'],800)
        hero['stack']={'value':800,'display':'800','approximate':False}
        r['controls']={'to_call':5000,'source':'call_button','hero_turn':True}
        c=get_context(r)
        self.assertTrue(c['shove_or_fold'])
        self.assertEqual(c['call'],800)

    def test_zero_price_when_nothing_is_visible(self):
        r=copy.deepcopy(self.snapshot)
        r['controls']={'to_call':None,'source':None,'hero_turn':True}
        for seat in r['seats']:seat['displayed_bet']=None
        c=get_context(r)
        self.assertEqual(c['call'],0)
        self.assertEqual(c['price_source'],'no_visible_bet')
        self.assertTrue(any('过牌成本' in x for x in c['assumptions']))

    def test_real_cfr_ev_against_known_value(self):
        # OOP range KK is drawing dead against hero's AA, so it checks; hero IP
        # then realises the whole pot with every action: check EV is exactly 120.
        r=call_engine(dict(mode='gto',hero=['Ah','As'],board=['Ac','Kd','7h','3s','2c'],
            ranges=['KK','AA'],pot=120,stack=200,call=0,hero_ip=True))
        self.assertTrue(r['converged'])
        self.assertAlmostEqual(sum(a['frequency'] for a in r['actions']),1,places=5)
        check=next(a for a in r['actions'] if a['action']=='check')
        self.assertAlmostEqual(check['ev'],120,delta=.05)

    def test_unreachable_observed_line_is_reported(self):
        # KK never bets into AA, so the observed bet node has zero reach.
        # The engine must say so instead of inventing a strategy for it.
        with self.assertRaises(RuntimeError) as caught:
            call_engine(dict(mode='gto',hero=['Ah','As'],board=['Ac','Kd','7h','3s','2c'],
                ranges=['KK','AA'],pot=120,stack=200,call=20,hero_ip=True))
        self.assertIn('zero reach',str(caught.exception))

    def test_end_to_end_hu_turn_gto(self):
        r=copy.deepcopy(self.turn_snapshot)
        r['seats']=[s for s in r['seats'] if s['seat'] in ('bottom','top')]
        r['seats'][0].update(action='bet',displayed_bet={'value':30000,'display':'30,000','approximate':False},
                             stack={'value':200000,'display':'200,000','approximate':False})
        r['seats'][1]['stack']={'value':180000,'display':'180,000','approximate':False}
        r['controls']={'to_call':30000,'source':'call_button','hero_turn':True}
        r['bet_presets']=[]
        a=analyze(r)
        self.assertEqual(a['status'],'ok')
        self.assertEqual(a['mode'],'gto')
        self.assertIn('单挑',a['mode_label'])
        self.assertAlmostEqual(sum(x['frequency'] for x in a['actions']),1,places=4)
        self.assertTrue(all(x['ev']>=0 for x in a['actions']))  # fold=0, call/raise > 0 here
        self.assertTrue(a['recommendation']['label'])
        self.assertIn(a['recommendation'],a['actions'])

    def test_tie_equity(self):
        r=call_engine(dict(mode='equity',hero=['2c','3d'],board=['Ah','Kh','Qh','Jh','Th'],ranges=['random','random'],samples=500))
        self.assertAlmostEqual(r['equity'],1/3,places=6)

    def test_automatic_estimate_is_not_labelled_gto(self):
        a=analyze(copy.deepcopy(self.snapshot))
        self.assertEqual(a['status'],'ok')
        self.assertEqual(a['mode'],'estimate')
        self.assertIn('非 GTO',a['mode_label'])
        self.assertTrue(all(x['frequency'] is None for x in a['actions']))
        self.assertGreater(len(a['actions']),3)

if __name__=='__main__':unittest.main()
