"""Native engine invariants independent of private screenshot fixtures."""
import unittest
from advisor import call_engine


class NativeSolver(unittest.TestCase):
    def test_split_pot_equity(self):
        r = call_engine(dict(mode='equity', hero=['2c','3d'], board=['Ah','Kh','Qh','Jh','Th'], ranges=['random','random'], samples=500))
        self.assertAlmostEqual(r['equity'], 1/3, places=6)

    def test_known_river_value(self):
        r = call_engine(dict(mode='gto', hero=['Ah','As'], board=['Ac','Kd','7h','3s','2c'], ranges=['KK','AA'], pot=120, stack=200, call=0, hero_ip=True))
        self.assertTrue(r['converged'])
        self.assertAlmostEqual(sum(a['frequency'] for a in r['actions']), 1, places=5)
        self.assertAlmostEqual(next(a for a in r['actions'] if a['action']=='check')['ev'], 120, delta=.05)

    def test_unreachable_line_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'zero reach'):
            call_engine(dict(mode='gto', hero=['Ah','As'], board=['Ac','Kd','7h','3s','2c'], ranges=['KK','AA'], pot=120, stack=200, call=20, hero_ip=True))
