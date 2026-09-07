from pathlib import Path
import json
root=Path(__file__).resolve().parent
cfg=json.loads((root/'config.json').read_text())
p=root/'apps/SillyTavern/public/scripts/extensions/third-party/Extension-WebSearch/index.js'
s=p.read_text(encoding='utf-8')
extract="""const page = new DOMParser().parseFromString(await data.text(), 'text/html');
        page.querySelectorAll('script, style, nav, header, footer, form, aside, noscript').forEach(x => x.remove());
        const clean = new Blob([page.body?.innerHTML || ''], {type: 'text/html'});
        const text = (await extractTextFromHTML(clean, 'p, h1, h2, h3, li, td')).slice(0, 6500);"""
s=s.replace("const text = await extractTextFromHTML(data, 'p');",extract)
s=s.replace("const text = (await extractTextFromHTML(data, 'p')).slice(0, 6500);",extract)
old="textBits.push(...Array.from(doc.querySelectorAll('#urls p.content')).map(x => x.textContent.trim()).filter(x => x));"
new="""for (const article of Array.from(doc.querySelectorAll('#urls article')).slice(0, %d)) {
            const link = article.querySelector('h3 a');
            const snippet = article.querySelector('p.content')?.textContent?.trim() || '';
            if (link) textBits.push(`${link.textContent.trim()} — ${link.href}\\n${snippet}`);
        }""" % cfg['SEARCH_RESULT_COUNT']
s=s.replace(old,new)
s=s.replace("console.debug('WebSearch: search failed');", "console.debug('WebSearch: search failed');\n            setExtensionPrompt(extensionPromptMarker, 'Web research was attempted but returned no usable results. Tell the user that live verification failed; do not invent current facts or citations.', extension_settings.websearch.position, extension_settings.websearch.depth);") if 'Web research was attempted but' not in s else s
s=s.replace("console.error('WebSearch: error while processing the request', error);", "console.error('WebSearch: error while processing the request', error);\n        setExtensionPrompt(extensionPromptMarker, 'Web research failed. Explain this limitation; never fabricate current facts or citations.', extension_settings.websearch.position, extension_settings.websearch.depth);") if 'Web research failed. Explain' not in s else s
p.write_text(s,encoding='utf-8')
manifest=root/'apps/SillyTavern/public/scripts/extensions/third-party/Extension-WebSearch/manifest.json'
m=json.loads(manifest.read_text()); m['auto_update']=False
manifest.write_text(json.dumps(m,indent=2))
# Native fetch timeout and response limit keep failed/oversized websites bounded.
p=root/'apps/SillyTavern/src/endpoints/search.js'
s=p.read_text(encoding='utf-8')
s=s.replace("fetch(url, { headers: visitHeaders })", "fetch(url, { headers: visitHeaders, signal: AbortSignal.timeout(15000), size: 4 * 1024 * 1024 })")
s=s.replace("fetch(searchUrl, { headers: visitHeaders })", "fetch(searchUrl, { headers: visitHeaders, signal: AbortSignal.timeout(20000), size: 4 * 1024 * 1024 })")
s=s.replace("fetch(mainPageUrl, { headers: visitHeaders })", "fetch(mainPageUrl, { headers: visitHeaders, signal: AbortSignal.timeout(5000), size: 4 * 1024 * 1024 })")
p.write_text(s,encoding='utf-8')
print('Web Search bounded page text and source URLs patched.')
