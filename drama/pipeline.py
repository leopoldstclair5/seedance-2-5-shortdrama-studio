import argparse,json,pathlib
def build(episode,scenes):
 if episode<1 or not scenes: raise ValueError("episode and scenes are required")
 return {"episode":episode,"draft_model":"seedance-2.5","final_model":"seedance-2.5","scenes":[{"id":i+1,"prompt":s,"draft":True} for i,s in enumerate(scenes)]}
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--episode",type=int,required=True);ap.add_argument("scenes",nargs="+");ap.add_argument("--out",default="episode-plan.json");a=ap.parse_args();pathlib.Path(a.out).write_text(json.dumps(build(a.episode,a.scenes),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
