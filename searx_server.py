import os, pathlib, sys, json
root=pathlib.Path(__file__).resolve().parent
cfg=json.loads((root/'config.json').read_text())
os.environ['SEARXNG_SETTINGS_PATH']=str(root/'runtime/searxng.yml')
os.environ['SEARXNG_VALKEY_URL']=''
os.chdir(root/'apps/searxng')
sys.path.insert(0,str(root/'apps/searxng'))
from searx.webapp import app
from waitress import serve
serve(app,host='127.0.0.1',port=cfg['SEARXNG_PORT'],threads=8)
