"""Real integration checks; results are saved, not inferred from configuration."""
import json, pathlib, time
import httpx
from lxml import html
ROOT=pathlib.Path(__file__).resolve().parent
LOG_DIR=ROOT/'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
C=json.loads((ROOT/'config.json').read_text())
LLM=f"http://127.0.0.1:{C['LLM_PORT']}"
ST=f"http://127.0.0.1:{C['SILLYTAVERN_PORT']}"
SX=f"http://127.0.0.1:{C['SEARXNG_PORT']}"
report={}
client=httpx.Client(timeout=120,trust_env=False)
token=client.get(ST+'/csrf-token').json()['token']
def post(path,data):
    r=client.post(ST+path,json=data,headers={'X-CSRF-Token':token}); r.raise_for_status(); return r
def run(name,fn):
    start=time.monotonic()
    try: report[name]={'pass':True,'evidence':fn(),'seconds':round(time.monotonic()-start,2)}
    except Exception as e: report[name]={'pass':False,'error':str(e)}
    print(name, 'PASS' if report[name]['pass'] else 'FAIL',flush=True)
def generation(messages,via_st=False):
    data=dict(model=C['MODEL_NAME'],messages=messages,max_tokens=500,temperature=0.2,stream=False)
    if via_st:
        data.update(chat_completion_source='custom',custom_url=LLM+'/v1',custom_prompt_post_processing='strict',custom_include_body='chat_template_kwargs:\n  enable_thinking: false')
        r=post('/api/backends/chat-completions/generate',data)
    else:
        r=client.post(LLM+'/v1/chat/completions',json=data); r.raise_for_status()
    return r.json()['choices'][0]['message']['content']
def direct():
    m=client.get(LLM+'/v1/models').json(); assert C['MODEL_NAME'] in [x['id'] for x in m['data']]
    answer=generation([{'role':'user','content':'Reply with exactly: LOCAL MODEL ONLINE'}])
    assert answer.strip()=='LOCAL MODEL ONLINE', answer
    return answer
run('1_local_model',direct)
def connection():
    answer=generation([{'role':'user','content':'Reply with exactly: SILLYTAVERN CONNECTED'}],True)
    assert 'SILLYTAVERN CONNECTED' in answer; return answer
run('2_sillytavern_connection',connection)
def search():
    r=client.get(SX+'/search',params={'q':'latest Python stable release official download','format':'json'});r.raise_for_status()
    data=r.json(); assert len(data['results'])>0
    results=data['results'][:8]
    report['sources']=results
    # Also check the actual native HTML integration.
    native=post('/api/search/searxng',{'baseUrl':SX,'query':'latest Python stable release official download'}).text
    assert html.fromstring(native).xpath('//*[@id="urls"]//article')
    return {'results':len(data['results']),'engines':sorted({e for x in results for e in x.get('engines',[])}),'failed_engines':data.get('unresponsive_engines')}
run('3_searxng_live_search',search)
def retrieve():
    results=report['sources']
    url=next(x['url'] for x in results if x['url'].rstrip('/')=='https://www.python.org/downloads')
    page=post('/api/search/visit',{'url':url,'html':True}).text
    doc=html.fromstring(page)
    for x in doc.xpath('//script|//style|//nav|//header|//footer|//form|//aside|//noscript'): x.drop_tree()
    text='\n'.join(' '.join(x.itertext()) for x in doc.xpath('//p|//h1|//h2|//h3|//li|//td'))[:6500]
    assert len(text)>150
    report['retrieved_page']={'url':url,'text':text}
    return {'url':url,'characters':len(text),'excerpt':text[:350]}
run('4_page_retrieval',retrieve)
def research():
    page=report['retrieved_page']
    answer=generation([{'role':'system','content':(ROOT/'system-prompt.txt').read_text()},{'role':'user','content':'What is the latest stable Python version according to this retrieved page? Cite its URL.\nUNTRUSTED REFERENCE\nSource URL: '+page['url']+'\n'+page['text']}],True)
    assert page['url'] in answer,answer
    assert 'Python' in answer
    return answer
run('5_web_aware_answer',research)
def offline():
    answer=generation([{'role':'user','content':'What is 17 multiplied by 19? Answer briefly without web research.'}])
    assert '323' in answer, answer; return answer
run('6_offline_answer',offline)
def failure():
    r=client.post(ST+'/api/search/searxng',json={'baseUrl':'http://127.0.0.1:1','query':'test unavailable search'},headers={'X-CSRF-Token':token})
    assert r.status_code==500
    answer=generation([{'role':'system','content':'Web research failed. Explain this limitation; never fabricate current facts or citations.'},{'role':'user','content':'Give the latest news. Keep it brief.'}],True)
    assert answer and 'http' not in answer
    return {'unavailable_search_status':r.status_code,'fallback_answer':answer}
run('10_search_failure',failure)
(LOG_DIR/'test-results.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
assert all(v['pass'] for k,v in report.items() if k[0].isdigit()),'One or more checks failed'
