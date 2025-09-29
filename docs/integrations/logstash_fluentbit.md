# Logstash & Fluent Bit integrations

This repo includes `logstash/pipeline.conf` and `fluentbit/fluent-bit.conf` as working examples.

## Logstash (filter/http) — recommended pipeline
- Use `logstash-filter-http` plugin (installed in our Logstash Dockerfile).
- Sample:

```conf
input {
  file {
    path => "/usr/share/logstash/sample_fix_messages.txt"
    start_position => "beginning"
    sincedb_path => "/dev/null"
    codec => plain { charset => "UTF-8" }
  }
}

filter {
  mutate { gsub => ["message", "\r", ""] }
  http {
    url => "http://fixparser:9000/parse"
    verb => "POST"
    body => { "raw" => "%{message}" }
    body_format => "json"
    headers => { "Content-Type" => "application/json" }
    target_body => "http_response"
  }
  json { source => "http_response" target => "fix_parsed" }
  mutate { rename => { "message" => "raw_fix" } }
}
output {
  stdout { codec => rubydebug }
}
```

**Why filter http**: it posts the event and attaches the parser response to the event, enabling Logstash to index both raw_fix and parsed fields.

## Fluent Bit (tail -> http)

```
[SERVICE]
    Flush        1
    Log_Level    info
[INPUT]
    Name   tail
    Path   /data/sample_fix_messages.txt
    Tag    fix
    DB     /fluent-bit/tail.db
    Read_from_head On
[OUTPUT]
    Name  http
    Match fix
    Host  fixparser
    Port 9000
    URI  /parse
    Format json
    Header Content-Type: application/json
```

**Note on Read_from_head**: Read_from_head On is convenient for demos (reads file from beginning) but in production you usually set it Off and rely on appends to the file. Also, Fluent Bit keeps a DB of offsets — delete it for a fresh run during testing.

## Production tips

- Avoid Read_from_head On in production unless you intentionally want reprocessing.

- For high volume, use a message queue (Kafka, Kinesis) between ingestion and parser for backpressure and durability.