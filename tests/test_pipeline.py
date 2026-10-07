import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]))
from drama.pipeline import build
class T(unittest.TestCase):
 def test_plan(self): self.assertEqual(build(1,["a"])["episode"],1)
if __name__=="__main__":unittest.main()
