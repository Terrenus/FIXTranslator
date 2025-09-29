# AWS integration (CloudWatch / Firehose)

Two common approaches:

## Option A — Kinesis Firehose with Lambda transform
1. Create a Firehose delivery stream.
2. Add a Lambda transformation that calls the parser (or embed the parser logic in the Lambda).
3. Output to S3 / Redshift / Elasticsearch / OpenSearch.

Minimal CloudFormation snippet (transform Lambda + Firehose skeleton):
```yaml
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  ParserTransformFunction:
    Type: AWS::Lambda::Function
    Properties:
      Handler: lambda_firehose_transform.lambda_handler
      Runtime: python3.11
      Code:
        ZipFile: |
          # small wrapper: import requests and post to parser; return transformed record
          import base64, json, requests
          def lambda_handler(event, context):
            out = {'records':[]}
            for r in event['records']:
              payload = base64.b64decode(r['data']).decode('utf-8')
              # call parser (self-hosted) OR run local parse logic
              parsed = {"flat": {"example":"value"}}
              out['records'].append({
                'recordId': r['recordId'],
                'result': 'Ok',
                'data': base64.b64encode(json.dumps(parsed).encode()).decode()
              })
            return out
      Timeout: 60

  # Firehose resource omitted for brevity – create stream with TransformationConfiguration pointing to ParserTransformFunction
```

## Option B — CloudWatch Logs (agent)

- Run CloudWatch Agent that tails parser output files (JSON).

- Use CloudWatch Logs Insights to query fields.

## Local testing

- Use LocalStack to emulate Firehose and CloudWatch in local demos. Set CLOUDWATCH_ENDPOINT_URL env var to http://localstack:4566 for boto3 in fixparser/exporters.py.

Tips:

- For low-latency environments prefer in-cluster transform (Lambda or Kinesis).

- Ensure proper IAM permissions for Lambda/Firehose.
