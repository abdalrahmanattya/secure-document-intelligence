#!/usr/bin/env bash
set -euo pipefail
: "${AWS_SMOKE_URL:?Terraform-derived API endpoint is required}"
: "${AWS_SMOKE_ID_TOKEN:?Set AWS_SMOKE_ID_TOKEN to a short-lived Cognito ID token}"
case "$AWS_SMOKE_URL" in https://*) ;; *) echo "API endpoint must use HTTPS" >&2; exit 2 ;; esac
headers=(-H "Authorization: Bearer ${AWS_SMOKE_ID_TOKEN}")
body='Invoice number: SYNTH-1
Total: $1.00
'
size=$(printf '%s' "$body" | wc -c | tr -d ' ')
digest=$(printf '%s' "$body" | sha256sum | awk '{print $1}')
payload=$(python3 -c 'import json,sys; print(json.dumps({"filename":"synthetic-invoice.txt","content_type":"text/plain","size":int(sys.argv[1]),"sha256":sys.argv[2],"tenant_id":"smoke-tenant"}))' "$size" "$digest")
created=$(curl --fail --silent --show-error --retry 3 "${headers[@]}" -H 'content-type: application/json' -H 'idempotency-key: smoke-synthetic-1' -X POST "$AWS_SMOKE_URL/v1/uploads" -d "$payload")
upload_url=$(printf '%s' "$created" | python3 -c 'import json,sys; print(json.load(sys.stdin)["upload"]["url"])')
document_id=$(printf '%s' "$created" | python3 -c 'import json,sys; print(json.load(sys.stdin)["document"]["id"])')
mapfile -t upload_fields < <(printf '%s' "$created" | python3 -c 'import json,sys; print("\n".join(f"{k}={v}" for k,v in json.load(sys.stdin)["upload"]["fields"].items()))')
form_args=(); for field in "${upload_fields[@]}"; do form_args+=( -F "$field" ); done
printf '%s' "$body" | curl --fail --silent --show-error -X POST "$upload_url" "${form_args[@]}" -F 'file=@-;filename=synthetic-invoice.txt;type=text/plain' >/dev/null
curl --fail --silent --show-error "${headers[@]}" -X POST "$AWS_SMOKE_URL/v1/documents/$document_id/process" >/dev/null
terminal=''
for _ in $(seq 1 30); do
  document=$(curl --fail --silent --show-error "${headers[@]}" "$AWS_SMOKE_URL/v1/documents/$document_id")
  terminal=$(printf '%s' "$document" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')
  case "$terminal" in APPROVED|NEEDS_REVIEW|REJECTED|FAILED) break ;; esac
  sleep 2
done
case "$terminal" in APPROVED|NEEDS_REVIEW) ;; *) echo "unexpected terminal state: $terminal" >&2; exit 1 ;; esac
extractions=$(curl --fail --silent --show-error "${headers[@]}" "$AWS_SMOKE_URL/v1/documents/$document_id/extractions")
audit=$(curl --fail --silent --show-error "${headers[@]}" "$AWS_SMOKE_URL/v1/documents/$document_id/audit-events")
printf '%s' "$extractions" | python3 -c 'import json,sys; items=json.load(sys.stdin)["items"]; assert items and all(item.get("source") and 0 <= float(item.get("confidence", -1)) <= 1 for item in items)'
printf '%s' "$audit" | python3 -c 'import json,sys; assert json.load(sys.stdin)["events"]'
correction='{"reviewer":"smoke-reviewer","decision":"APPROVED","corrections":{"invoice_number":"SYNTH-1-CORRECTED"},"comment":"synthetic verification"}'
curl --fail --silent --show-error "${headers[@]}" -H 'content-type: application/json' -X POST "$AWS_SMOKE_URL/v1/documents/$document_id/reviews" -d "$correction" >/dev/null
curl --fail --silent --show-error "${headers[@]}" -X DELETE "$AWS_SMOKE_URL/v1/documents/$document_id" -o /dev/null -w '%{http_code}' | grep -qx 204
! curl --silent --show-error "${headers[@]}" "$AWS_SMOKE_URL/v1/documents/$document_id" >/dev/null
artifact="${RUNNER_TEMP:-/tmp}/secure-document-intelligence-smoke-${document_id}.json"
python3 -c 'import json,sys; json.dump({"document_id":sys.argv[1],"terminal_state":sys.argv[2],"extraction_fields":len(json.loads(sys.argv[3])["items"]),"audit_events":len(json.loads(sys.argv[4])["events"]),"deleted":True},open(sys.argv[5],"w"),indent=2)' "$document_id" "$terminal" "$extractions" "$audit" "$artifact"
echo "sanitized evidence: $artifact"
