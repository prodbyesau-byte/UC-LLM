import json, pathlib, secrets
import yaml
ROOT = pathlib.Path(__file__).resolve().parent
def write(path, text):
    p=ROOT/path; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8')
cfg = dict(MODEL_PATH='models/Qwen3.5-4B-Q6_K.gguf', MODEL_NAME='Qwen3.5-4B-Q6_K', LLM_PORT=5001, SILLYTAVERN_PORT=8000, SEARXNG_PORT=8080, CONTEXT_SIZE=16384, CPU_THREADS=6, SEARCH_RESULT_COUNT=8, WEB_VISIT_COUNT=3, MAX_SEARCH_ITERATIONS=3)
if not (ROOT/'config.json').exists(): write('config.json',json.dumps(cfg,indent=2))
cfg=json.loads((ROOT/'config.json').read_text())
write('.gitignore','.env\napps/\nmodels/\nruntime/\nlogs/\ndownloads/\n__pycache__/\n')
if not (ROOT/'.env').exists(): write('.env','# Optional only; leave empty for free local search.\nTAVILY_API_KEY=\n')
write('.env.example','TAVILY_API_KEY=\n')
secretfile=ROOT/'runtime/searx-secret.txt'
if not secretfile.exists(): secretfile.write_text(secrets.token_hex(32))
search={'use_default_settings': {'engines': {'keep_only':['duckduckgo','google','bing','brave','wikipedia','github','stackoverflow'] }},'general':{'instance_name':'Local Agent Search'},'server':{'secret_key':secretfile.read_text(),'bind_address':'127.0.0.1','port':cfg['SEARXNG_PORT'],'limiter':False,'image_proxy':False},'search':{'formats':['html','json'],'safe_search':0},'outgoing':{'request_timeout':6.0,'max_request_timeout':12.0},'engines':[{'name':x,'disabled':False} for x in ['duckduckgo','google','bing','brave','wikipedia','github','stackoverflow']]}
write('runtime/searxng.yml',yaml.safe_dump(search))
# Windows lacks pwd; only the optional Valkey error log uses it.
p=ROOT/'apps/searxng/searx/valkeydb.py'
s=p.read_text(); s=s.replace('import pwd','import getpass').replace('_pw = pwd.getpwuid(os.getuid())','_username = getpass.getuser()').replace('logger.exception("[%s (%s)] can\'t connect valkey DB ...", _pw.pw_name, _pw.pw_uid)','logger.exception("[%s] can\'t connect valkey DB ...", _username)'); p.write_text(s)
p=ROOT/'apps/searxng/searx/webutils.py'
s=p.read_text().replace('file_list.append(str(f.relative_to(static_path)))','file_list.append(f.relative_to(static_path).as_posix())').replace('result_templates.add(f)','result_templates.add(f.replace(chr(92), "/"))')
p.write_text(s)
p=ROOT/'apps/SillyTavern/config.yaml'
st=yaml.safe_load(p.read_text() if p.exists() else (ROOT/'apps/SillyTavern/default/config.yaml').read_text())
st.update(listen=False,listenAddress={'ipv4':'127.0.0.1','ipv6':'::1'},port=cfg['SILLYTAVERN_PORT'])
st['browserLaunch']['enabled']=False
p.write_text(yaml.safe_dump(st,sort_keys=False))
print('Local-only configuration written.')
