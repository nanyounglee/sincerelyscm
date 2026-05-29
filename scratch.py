import urllib.request, json
req = urllib.request.Request('https://api.airtable.com/v0/appkRWtF2j99XgBTq/tblUYmhOvtHGJ9NO3?maxRecords=1&returnFieldsByFieldId=true', headers={'Authorization': 'Bearer patM0xqBHeF8WJIts'})
res = urllib.request.urlopen(req)
data = json.loads(res.read())
print(json.dumps(data, indent=2))
