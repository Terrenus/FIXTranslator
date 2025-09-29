# use curl to call parser
resp=$(curl -s -X POST "http://localhost:9000/parse" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg raw '8=FIX.4.4|9=200|35=8|49=BROKER03|56=CLIENT12|34=216|52=20250927-12:30:06.456|11=12345|17=56789|39=2|150=F|55=EUR/USD|54=1|38=1000000|44=1.1850|60=20250927-12:30:06|10=128|' '{"raw":$raw}')")

# extract the 'flat' JSON (jq)
flat=$(echo "$resp" | jq -c '.flat')

# send to Splunk HEC
curl -k -H "Authorization: Splunk $SPLUNK_TOKEN" \
     -H "Content-Type: application/json" \
     -d "{\"event\": $flat, \"sourcetype\":\"fix:parsed\"}" \
     https://localhost:8088/services/collector