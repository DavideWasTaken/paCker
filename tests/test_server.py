import json,pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from serve import solve
class ServerTests(unittest.TestCase):
    def test_native_round_trip(self):
        status,out=solve(json.dumps({'boxes':[{'id':'b','width':180,'length':180,'height':30}],
            'items':[{'id':'bar','width':220,'length':30,'height':20}]}).encode())
        self.assertEqual(status,200)
        self.assertEqual(out.get('status'),'complete')
        self.assertEqual(out['bins'][0]['items'][0]['angle'],45)
    def test_invalid_json(self):
        status,out=solve(b'{');self.assertEqual(status,400);self.assertIn('error',out)
    def test_input_cap(self):
        status,out=solve(b' '*1048577);self.assertEqual(status,413)
if __name__=='__main__':unittest.main()
