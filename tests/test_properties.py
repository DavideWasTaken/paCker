import copy,json,pathlib,random,subprocess,sys,unittest
from validate_result import validate,intersection_area,full_support
ROOT=pathlib.Path(__file__).resolve().parents[1]
EXE=ROOT/'build'/('packer.exe' if sys.platform=='win32' else 'packer')

def run(data):
    p=subprocess.run([str(EXE)],input=json.dumps(data),text=True,capture_output=True,timeout=15)
    if p.returncode:raise AssertionError(p.stdout+p.stderr)
    return json.loads(p.stdout)

class GeometryProperties(unittest.TestCase):
    def test_independent_clipping(self):
        self.assertEqual(intersection_area([(0,0),(2,0),(2,2),(0,2)],[(1,1),(3,1),(3,3),(1,3)]),1)
        self.assertEqual(intersection_area([(0,0),(1,0),(1,1),(0,1)],[(1,0),(2,0),(2,1),(1,1)]),0)
    def test_full_support_coplanar_union_and_gap(self):
        a=dict(x=20,y=20,z=0,width=40,length=40,height=10,angle=0)
        b=dict(a,x=60)
        p=dict(a,x=40,z=10,width=80)
        self.assertTrue(full_support(p,[a,b]))
        self.assertFalse(full_support(p,[a,dict(b,x=61)]))
        self.assertFalse(full_support(p,[a,dict(b,height=9)]))

    def test_seeded_solutions(self):
        rng=random.Random(97201)
        for seed in range(80):
            data={'boxes':[{'id':'b'+str(k),'width':rng.randint(80,300),'length':rng.randint(80,300),
                    'height':rng.randint(50,150),'max_weight':rng.randint(200,2000),'quantity':rng.choice([-1,1,2]),'cost':k+1} for k in range(3)],
                  'items':[{'id':'p'+str(k),'width':rng.randint(10,220),'length':rng.randint(10,100),
                    'height':rng.randint(10,70),'weight':rng.randint(10,300),'quantity':rng.randint(1,3),
                    'rotation':rng.choice(['none','flat','any']),'diagonal':rng.choice([True,False])} for k in range(rng.randint(1,8))],
                  'options':{'seed':seed,'restarts':3,'max_candidates':10000,'time_limit_ms':5000}}
            with self.subTest(seed=seed):
                result=run(data);self.assertEqual(validate(data,result),[])
                self.assertLessEqual(result['stats']['candidates'],10000)
    def test_long_bridge_cannot_span_a_small_real_gap(self):
        d={'boxes':[{'id':'box','width':1000000,'length':1.002,'height':11,'quantity':1}],
           'items':[{'id':'base','width':499999.9985,'length':1,'height':10,'quantity':2,'rotation':'none','diagonal':False},
                    {'id':'bridge','width':999999.998,'length':1,'height':1,'rotation':'none','diagonal':False}],
           'options':{'gap':.001,'restarts':1,'time_limit_ms':5000,'max_candidates':1000,'support_mode':'full_base'}}
        a=dict(x=250000.00025,y=.501,z=0,width=499999.9985,length=1,height=10,angle=0)
        b=dict(a,x=749999.99975)
        p=dict(a,x=500000,z=10,width=999999.998,height=1)
        self.assertFalse(full_support(p,[a,b]))
        o=run(d)
        self.assertEqual(len(o['unpacked']),1)
        self.assertEqual(validate(d,o),[])
    def test_determinism(self):
        d={'boxes':[{'id':'b','width':180,'length':180,'height':30}],
           'items':[{'id':'bar','width':220,'length':30,'height':20,'quantity':3}],
           'options':{'seed':40,'max_candidates':5000,'time_limit_ms':5000}}
        a,b=run(d),run(d)
        for p in [a,b]:p['stats'].pop('elapsed_ms')
        self.assertEqual(a,b)
    def test_diagonal_edge_contacts_across_scales(self):
        for scale in (0.001, 1, 1000):
            d={'boxes':[{'id':'square','width':100*scale,'length':100*scale,'height':scale,'quantity':1}],
               'items':[{'id':'bar','width':120*scale,'length':5*scale,'height':scale,'quantity':4}],
               'options':{'restarts':4,'max_candidates':100000,'time_limit_ms':5000}}
            o=run(d)
            with self.subTest(scale=scale):
                self.assertEqual(o['unpacked'],[])
                self.assertEqual(len(o['bins']),1)
                self.assertEqual(validate(d,o),[])
    def test_orthogonal_item_contacts_with_oblique_placed_items(self):
        # Permission belongs to the phase, not just the current item: the
        # square must retain its contact candidates against oblique bars.
        # Actual oblique edge-contact probes remain unchanged. Removing the
        # duplicate square pose saves one orthogonal probe per restart.
        for rotation, candidates in (('none',682),('flat',848),('any',848)):
            d={'boxes':[dict(id='box',width=100,length=100,height=1,quantity=1)],
               'items':[dict(id='bar',width=120,length=5,height=1,quantity=4,rotation='flat',diagonal=True),
                        dict(id='square',width=10,length=10,height=1,rotation=rotation,diagonal=False)],
               'options':dict(restarts=4,max_candidates=100000,time_limit_ms=5000)}
            o=run(d)
            with self.subTest(rotation=rotation):
                self.assertEqual(o['unpacked'],[])
                self.assertEqual(o['stats']['candidates'],candidates)
                self.assertEqual(o['stats']['restarts'],4)
                self.assertFalse(o['stats']['budget_exhausted'])
                self.assertFalse(o['stats']['timed_out'])
                self.assertEqual([p['angle'] for p in o['bins'][0]['items']], [135]*4+[0])
                self.assertEqual(validate(d,o),[])
    def test_gap_and_budget(self):
        d={'boxes':[{'id':'b','width':100,'length':100,'height':20}],
           'items':[{'id':'a','width':49,'length':49,'height':20,'quantity':5}],
           'options':{'gap':2,'max_candidates':20,'time_limit_ms':5000}}
        o=run(d);self.assertEqual(validate(d,o),[]);self.assertLessEqual(o['stats']['candidates'],20)
    def test_global_time_budget(self):
        d={'boxes':[{'id':'b','width':300,'length':300,'height':200}],
           'items':[{'id':'a','width':63,'length':23,'height':17,'quantity':256}],
           'options':{'angle_step':1,'restarts':64,'max_candidates':100000000,'time_limit_ms':1}}
        o=run(d);self.assertTrue(o['stats']['timed_out']);self.assertLess(o['stats']['elapsed_ms'],150)
        self.assertEqual(validate(d,o),[])

if __name__=='__main__':unittest.main()
