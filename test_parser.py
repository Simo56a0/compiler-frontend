import json, urllib.request

modes = ['rd', 'll1', 'slr', 'lalr']
source = 'x = 5; print(x);'

print("Testing all parser modes:")
for mode in modes:
    req = urllib.request.Request('http://localhost:8000/parse', 
        data=json.dumps({'source': source, 'mode': mode}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    success = "✓" if data.get('success') else "✗"
    print(f"{success} {data.get('parser')}: {data.get('success')}")
