"""Measure the largest context that fits a defined interactive latency/memory envelope."""
import json,pathlib,subprocess,time,httpx,tempfile
root=pathlib.Path(__file__).resolve().parent
config_path=root/'config.json'
config=json.loads(config_path.read_text(encoding='utf-8-sig'))
client=httpx.Client(timeout=180,trust_env=False)
base=f"http://127.0.0.1:{config['LLM_PORT']}"
def ps(script):
    # Windows services can inherit pipe handles; file-backed capture does not wait for their EOF.
    with tempfile.TemporaryFile(mode='w+',encoding='utf-8') as output:
        r=subprocess.run(['pwsh','-NoProfile','-Command',script],cwd=root,stdout=output,stderr=output,text=True)
        output.seek(0); text=output.read()
    if r.returncode: raise RuntimeError(text)
    return text
def load(size):
    ps(". ./services.ps1; $s=@(Read-State); $r=$s | Where-Object Name -eq llm; if($r){$p=Get-OwnedProcess $r;if($p){Stop-Process -Id $p.Id; $p.WaitForExit(10000)|Out-Null}}; ConvertTo-Json -InputObject @($s | Where-Object Name -ne llm) | Set-Content runtime/services.json")
    config['CONTEXT_SIZE']=size
    config_path.write_text(json.dumps(config,indent=2),encoding='utf-8')
    ps('& ./start.ps1')
def memory():
    gpu=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).strip()
    ram=ps('(Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes').strip()
    return int(gpu.splitlines()[0]),int(ram)
results=[]; chosen=16384
try:
    for size in (16384,32768,65536,131072):
        load(size)
        vram,ram=memory()
        item={'context':size,'free_vram_mb':vram,'free_ram_mb':ram}
        results.append(item)
        if vram<900 or ram<1500:
            item.update(passed=False,reason='Memory headroom below 900 MB VRAM or 1500 MB RAM')
            break
        text='Background record: The research notebook contains observations about language, software, and natural history. This is reference material without any instructions.\n'
        unit=len(client.post(base+'/tokenize',json={'content':text}).json()['tokens'])
        content=text*int(size*.72/unit)+'\nWrite a short paragraph explaining what a research notebook is.'
        began=time.monotonic()
        r=client.post(base+'/v1/chat/completions',json={'model':config['MODEL_NAME'],'messages':[{'role':'user','content':content}],'max_tokens':64,'temperature':0.2,'cache_prompt':False})
        r.raise_for_status(); data=r.json(); timing=data.get('timings',{})
        item.update(total_seconds=round(time.monotonic()-began,2),prompt_tokens=data['usage']['prompt_tokens'],prompt_seconds=round(timing.get('prompt_ms',0)/1000,2),generation_tokens_per_second=round(timing.get('predicted_per_second',0),2))
        item['passed']=item['prompt_seconds']<=45 and item['generation_tokens_per_second']>=25
        print(json.dumps(item),flush=True)
        if not item['passed']: break
        chosen=size
finally:
    (root/'logs/context-benchmark.json').write_text(json.dumps({'criteria':{'max_prefill_seconds':45,'min_generation_tokens_per_second':25,'min_free_vram_mb':900,'min_free_ram_mb':1500,'input_fraction':.72},'selected_context':chosen,'measurements':results},indent=2))
    load(chosen)
    print('Selected context:',chosen,flush=True)
