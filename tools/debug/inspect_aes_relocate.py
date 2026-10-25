import re

with open('records/2026-10-18/AES_Performance_and_Reliability.html', encoding='utf-8', errors='ignore') as f:
    html = f.read()

m = re.findall(r'.{0,150}relocate.{0,250}', html, re.I)
print('Relocate matches count:', len(m))
for x in m[:4]:
    print('---')
    print(x)
