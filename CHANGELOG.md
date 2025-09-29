# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.1.0] - 2025-09-29
### Added
- Initial public demo: FastAPI parser, basic UI, exporters for Splunk/Datadog/CloudWatch (helpers).
- Example integration configs: Logstash pipeline, Fluent Bit config.
- Docker compose demo (parser, Logstash, Fluent Bit, LocalStack).
- validate.sh script and sample FIX messages.
- Documentation and integration guides.

### Fixed
- Parser robust to Fluent Bit / Logstash shapes (accepts `raw`, `log`, `message`, arrays).
