import json, urllib.request

code = """age = 20
if age >= 18:
    status = "adult"
elif age > 12:
    status = "teen"
else:
    status = "child"
print(status)"""

req = urllib.request.Request('http://localhost:8000/parse', 
    data=json.dumps({'source': code, 'mode': 'rd'}).encode(),
    headers={'Content-Type': 'application/json'}, method='POST')

try:
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    
    print('═' * 60)
    print('STAGE 1: LEXICAL ANALYSIS')
    print('═' * 60)
    print(f"✓ Tokens produced: {data['stage1_lexer']['token_count']}")
    print(f"✓ Lexer errors: {len(data['stage1_lexer']['errors'])}")
    
    print('\n' + '═' * 60)
    print('STAGE 2: SYNTAX ANALYSIS')
    print('═' * 60)
    print(f"✓ Parser: {data['stage2_parser']['parser']}")
    print(f"✓ Success: {data['stage2_parser']['success']}")
    
    if data['stage2_parser']['error']:
        print(f"✗ Error: {data['stage2_parser']['error']}")
    else:
        print(f"✓ AST generated successfully")
        
except Exception as e:
    print(f"Error: {e}")
