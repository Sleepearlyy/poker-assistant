import unittest
from core import amount,numeric,blinds,action,card_rank,Stability,visible_pot,assign_roles,facing_button
def row(text,score=.99,box=None):
    item={'text':text,'score':score}
    if box is not None:item['box']=box
    return item
class Tests(unittest.TestCase):
    def test_amount(self):
        self.assertEqual(amount('14.97K')['value'],14970)
        self.assertTrue(amount('148K')['approximate'])
        self.assertEqual(amount('10,000')['value'],10000)
        self.assertIsNone(amount('Next 75/150'))
        self.assertEqual(amount('0')['value'],0)
    def test_unknown_and_ambiguous(self):
        self.assertIsNone(numeric([]))
        self.assertIsNone(numeric([row('100',.4)]))
        self.assertIsNone(numeric([row('100'),row('1000')]))
    def test_blinds(self):
        self.assertEqual(blinds([row('盲注：500/1000')])['big'],1000)
        self.assertIsNone(blinds([row('0/100')]))
    def test_action(self):
        self.assertEqual(action([row('SB'),row('50')])['displayed_bet']['value'],50)
        self.assertEqual(action([row('Call 100')])['action'],'call')
        self.assertEqual(action([row('弃 牌')])['action'],'fold')
        self.assertIsNone(action([row('Fold')])['displayed_bet'])
        blind=action([
            row('大盲',box=[[0,0],[40,0],[40,12],[0,12]]),
            row('1000',box=[[0,14],[48,14],[48,26],[0,26]]),
            row('6000',box=[[0,90],[60,90],[60,104],[0,104]])])
        self.assertEqual(blind['action'],'big_blind')
        self.assertEqual(blind['displayed_bet']['value'],1000)
    def test_middle_button_becomes_all_in(self):
        shoved=facing_button('all_in')
        self.assertEqual(shoved['source'],'all_in_button')
        self.assertTrue(shoved['hero_turn'])
        self.assertIsNone(shoved['to_call'])
        self.assertEqual(facing_button('ALL_IN 800')['to_call'],800)
        self.assertEqual(facing_button('跟注 1000')['source'],'call_button')
        self.assertEqual(facing_button('弃牌 ALLIN')['source'],'all_in_button')
        self.assertEqual(facing_button('弃牌 跟注 1000 ALL IN')['source'],'call_button')
        self.assertFalse(facing_button('')['hero_turn'])
        self.assertEqual(facing_button('过牌')['to_call'],0)
    def test_cards(self):
        self.assertEqual(card_rank([row('10'),row('10')])['rank'],'10')
        self.assertIsNone(card_rank([row('10'),row('7')]))
        self.assertIsNone(card_rank([row('10000')]))
        self.assertEqual(card_rank([row('4.')])['rank'],'4')
        self.assertEqual(card_rank([row('I',.62)])['rank'],'J')
        self.assertEqual(card_rank([row('8',.4)])['rank'],'8')
        self.assertIsNone(card_rank([row('8',.2)]))
    def test_preflop_pot_is_the_sum_of_visible_bets(self):
        hero={'card':'J♠','status':'recognized'}
        empty={'card':None,'status':'unknown'}
        bet=lambda n:{'value':n}
        table={'hero_cards':[hero,hero],'board_cards':[empty]*5,
               'seats':[{'displayed_bet':bet(500)},{'displayed_bet':bet(1000)},{'displayed_bet':None}]}
        self.assertEqual(visible_pot(table)['value'],1500)
        table['board_cards'][0]={'card':None,'status':'unreadable'}
        self.assertIsNone(visible_pot(table))
    def test_roles_follow_the_button(self):
        def seat(name, present=True, blind=None):
            return {'seat':name,'presence':'occupied' if present else 'empty_or_unreadable','blind_role':blind}
        seats=[seat(n) for n in ['top','upper_right','lower_right','bottom','lower_left','upper_left']]
        roles=assign_roles(seats,'bottom')
        self.assertEqual(roles['bottom'],'按钮')
        self.assertEqual(roles['lower_left'],'小盲')
        self.assertEqual(roles['upper_left'],'大盲')
        self.assertEqual(roles['top'],'枪口')
        self.assertEqual(roles['upper_right'],'劫位')
        self.assertEqual(roles['lower_right'],'关煞')
        seats[0]['presence']='empty_or_unreadable'
        roles=assign_roles(seats,'bottom')
        self.assertIsNone(roles['top'])
        self.assertEqual(roles['upper_right'],'枪口')
        self.assertEqual(roles['lower_right'],'关煞')
        hu=[seat('bottom',blind='small_blind'),seat('lower_left',blind='big_blind')]
        roles=assign_roles(hu,'lower_left')
        self.assertEqual(roles['bottom'],'按钮')
        self.assertEqual(roles['lower_left'],'大盲')
    def test_no_stale_state(self):
        s=Stability(2)
        self.assertEqual(s.observe('pot',100),'pending')
        self.assertEqual(s.observe('pot',100),'confirmed')
        self.assertEqual(s.observe('pot',None),'unknown')
        self.assertEqual(s.observe('pot',200),'pending')
if __name__=='__main__': unittest.main()
