import json, pathlib, shutil, datetime
root=pathlib.Path(__file__).resolve().parent.parent
user=root/'apps/SillyTavern/data/default-user'
settings=user/'settings.json'
backup=root/'runtime/backups'/('skin-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,exist_ok=True)
shutil.copy2(settings,backup/'settings.json')
s=json.loads(settings.read_text(encoding='utf-8'))
theme=json.loads((user/'themes/Dark Lite.json').read_text(encoding='utf-8'))
theme.update(name='N2LLM',main_text_color='rgba(41,39,34,1)',italics_text_color='rgba(130,123,114,1)',quote_text_color='rgba(117,104,90,1)',underline_text_color='rgba(117,104,90,1)',blur_tint_color='rgba(243,239,232,1)',chat_tint_color='rgba(250,248,244,1)',border_color='rgba(91,80,67,0.16)',user_mes_blur_tint_color='rgba(232,225,216,1)',bot_mes_blur_tint_color='rgba(255,253,249,1)',blur_strength=0,chat_width=82,font_scale=1,shadow_width=0,custom_css=(root/'desktop/neon.css').read_text(encoding='utf-8'))
(user/'themes'/f"{theme['name']}.json").write_text(json.dumps(theme,indent=2,ensure_ascii=False),encoding='utf-8')
s['power_user'].update({k:v for k,v in theme.items() if k!='name'})
s['power_user']['theme']=theme['name']
settings.write_text(json.dumps(s,indent=2,ensure_ascii=False),encoding='utf-8')
ui=root/'apps/SillyTavern/public/scripts/extensions/third-party/LocalAgentUI'
ui.mkdir(parents=True,exist_ok=True)
font_dir=root/'apps/SillyTavern/public/assets/fonts'
font_dir.mkdir(parents=True,exist_ok=True)
for font in ('SpaceGrotesk.ttf','BodoniModa.ttf','IBMPlexMono.ttf'):
    shutil.copy2(root/'desktop/assets/fonts'/font, font_dir/font)
shutil.copy2(root/'assets/branding/n2llm-logo.png', root/'apps/SillyTavern/public/img/n2llm-logo.png')
shutil.copy2(root/'desktop/local-agent-ui.js',ui/'index.js')
shutil.copy2(root/'desktop/local-agent-ui.css',ui/'style.css')
(ui/'manifest.json').write_text(json.dumps({
    'display_name':'Local Agent UI',
    'loading_order':10,
    'requires':[],
    'js':'index.js',
    'css':'style.css',
    'author':'Local Agent',
    'version':'1.0.1',
    'auto_update':False
},indent=2),encoding='utf-8')
print('LUXE theme installed. Previous settings backed up:',backup)
