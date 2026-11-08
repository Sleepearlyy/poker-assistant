"""Regression checks against user-provided screenshots and a synthetic vacant seat."""
import unittest
from pathlib import Path
import cv2
from reader import Reader, load_image, trim_titlebar, load_layout

ROOT=Path(__file__).resolve().parent
class Images(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all((ROOT/name).is_file() for name in ('sample-wide.png','sample-tall.jpg')):
            raise unittest.SkipTest('Private screenshot fixtures are not distributed')
        cls.wide=trim_titlebar(load_image(ROOT/'sample-wide.png'))
        _,cls.layout=load_layout(ROOT/'layouts.json',cls.wide,'auto')
        cls.reader=Reader(cls.layout)

    def test_wide(self):
        self.assertEqual(self.wide.shape[:2],(1010,1920))
        r=self.reader.scan(self.wide)
        self.assertEqual([s['stack']['value'] for s in r['seats']], [223060,85420,331330,148000,17750,195590])
        self.assertEqual(r['blinds']['small'],500)
        self.assertEqual(r['blinds']['big'],1000)
        self.assertEqual(r['pot']['value'],10000)
        self.assertEqual([x['card'] for x in r['hero_cards']],['4♥','Q♦'])
        self.assertEqual([x['card'] for x in r['board_cards']],['10♣','7♦','A♦',None,None])
        self.assertEqual(r['seats'][2]['action'],'fold')

    def test_synthetic_empty_slot(self):
        frame=self.wide.copy()
        h,w=frame.shape[:2]
        for field in ('stack','name','action'):
            x1,y1,x2,y2=self.layout['seats'][0][field]
            frame[int(y1*h):int(y2*h)+1,int(x1*w):int(x2*w)+1]=(32,90,20)
        r=self.reader.scan(frame)
        self.assertEqual(r['recognized_players'],5)
        self.assertEqual(r['seats'][0]['presence'],'empty_or_unreadable')
        self.assertIsNone(r['seats'][0]['stack'])
        self.assertIsNone(r['seats'][0]['displayed_bet'])

    def test_scaled(self):
        frame=trim_titlebar(cv2.resize(load_image(ROOT/'sample-wide.png'),None,fx=.75,fy=.75))
        r=self.reader.scan(frame)
        self.assertEqual(r['pot']['value'],10000)
        self.assertEqual(r['recognized_players'],6)
        self.assertEqual(r['blinds']['big'],1000)

    def test_tall(self):
        frame=trim_titlebar(load_image(ROOT/'sample-tall.jpg'))
        _,layout=load_layout(ROOT/'layouts.json',frame,'auto')
        reader=Reader(layout)
        r=reader.scan(frame)
        self.assertEqual([s['stack']['value'] for s in r['seats']],[14970,5725,4225,14560,15380,5000])
        self.assertEqual([s['displayed_bet']['value'] if s['displayed_bet'] else None for s in r['seats']], [None,None,50,100,100,None])
        self.assertEqual(r['blinds']['big'],100)
        self.assertIsNone(r['pot'])
        self.assertTrue(all(c['card'] is None for c in r['hero_cards']+r['board_cards']))

if __name__=='__main__': unittest.main()
