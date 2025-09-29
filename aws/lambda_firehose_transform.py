# aws/lambda_firehose_transform.py
import base64
import json
from fixparser.parser import FixDictionary, parse_fix_message, flatten, human_summary

fd = FixDictionary()
# Option: bundle dictionaries in the lambda layer or EFS and load on cold start

def lambda_handler(event, context):
    output = {'records': []}
    for rec in event['records']:
        payload = base64.b64decode(rec['data']).decode('utf-8')
        parsed = parse_fix_message(payload, dict_obj=fd)
        flat = flatten(parsed['parsed_by_tag'])
        out = json.dumps({"flat": flat, "summary": human_summary(flat)})
        output['records'].append({
            'recordId': rec['recordId'],
            'result': 'Ok',
            'data': base64.b64encode(out.encode('utf-8')).decode('utf-8')
        })
    return output
