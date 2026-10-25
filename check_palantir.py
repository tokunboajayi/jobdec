import re

with open('records/2026-10-18/Palantir_Product_Designer_Internship_US_Government_New_York_NY_1d_old.html', encoding='utf-8', errors='ignore') as f:
    html = f.read()

iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
print('iframes count:', len(iframes))
for src in iframes:
    print(' ', src)

hcap = re.findall(r'[^>]*hcaptcha[^<]*', html, re.I)
print('hcap matches:', len(hcap))
for h in hcap[:5]:
    print(' ', h[:100])
