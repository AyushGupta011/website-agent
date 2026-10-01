import urllib.request
import json
import time

try:
    req = urllib.request.Request(
        'http://localhost:8000/generate',
        data=b'{"url": "dropmytrack.com"}',
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    res = json.loads(urllib.request.urlopen(req).read())
    sid = res['session_id']
    print('SID:', sid)

    while True:
        status_res = json.loads(urllib.request.urlopen(f'http://localhost:8000/status/{sid}').read())
        status = status_res.get('status')
        print("Status:", status, flush=True)
        if status == 'error':
            print("ERROR:", flush=True)
            print(status_res.get('error'), flush=True)
            break
        if status == 'complete':
            print("DONE")
            break
        time.sleep(2)
except Exception as e:
    print("Script Error:", e)
