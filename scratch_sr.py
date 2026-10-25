import re

with open('records/2026-10-18/Wellmark_Software_Engineer_Intern_Metadata_Enablement_Team_Des_Moines_IA_14d_old.html', encoding='utf-8', errors='ignore') as f:
    html = f.read()

title = re.search(r'<title>(.*?)</title>', html, re.I)
print('Title:', title.group(1) if title else 'None')
print('Length:', len(html))
links = [x for x in re.findall(r'https?://[^\s"\'<>]+', html) if 'smartrecruiters' in x]
print('SR links count:', len(links))
for l in links[:10]:
    print(' ', l)

buttons = re.findall(r'<button[^>]*>.*?</button>', html, re.I | re.S)
print('Buttons count:', len(buttons))
for b in buttons[:5]:
    print(' ', b[:150])
