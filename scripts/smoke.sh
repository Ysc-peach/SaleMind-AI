#!/usr/bin/env sh
# Read-only smoke check for a deployed SalesMind AI instance.
#
# Answers the only question that matters after a deploy: is this instance
# actually serving the business API, or merely answering /healthz?
#
# Usage:
#   SMOKE_USERNAME=admin SMOKE_PASSWORD='...' sh scripts/smoke.sh
#   SMOKE_BASE_URL=http://salesmind.internal:8080 SMOKE_USERNAME=... sh scripts/smoke.sh
#
# Never writes data and never prints the password or token. Exit code 1 means at
# least one check failed.

set -eu

BASE_URL="${SMOKE_BASE_URL:-http://127.0.0.1:8080}"
BASE_URL="${BASE_URL%/}"
USERNAME="${SMOKE_USERNAME:-}"
PASSWORD="${SMOKE_PASSWORD:-}"
# Probing a container name (http://nginx) sends Host: nginx, which
# ALLOWED_HOSTS rejects. Set this to the hostname users actually type.
SMOKE_HOST="${SMOKE_HOST:-}"

if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
    echo "Set SMOKE_USERNAME and SMOKE_PASSWORD before running the smoke check." >&2
    exit 2
fi

failures=0
body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT

# status_of METHOD PATH [JSON] [TOKEN]
status_of() {
    method="$1"; path="$2"; payload="${3:-}"; token="${4:-}"
    set -- -s -o "$body_file" -w '%{http_code}' -X "$method" --max-time 20
    if [ -n "$SMOKE_HOST" ]; then
        set -- "$@" -H "Host: $SMOKE_HOST"
    fi
    if [ -n "$token" ]; then
        set -- "$@" -H "Authorization: Bearer $token"
    fi
    if [ -n "$payload" ]; then
        set -- "$@" -H 'Content-Type: application/json' -d "$payload"
    fi
    curl "$@" "$BASE_URL$path" || echo 0
}

# json_field NAME
json_field() {
    sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$body_file" | head -n 1
}

check() {
    name="$1"; expected="$2"; actual="$3"
    for want in $expected; do
        if [ "$actual" = "$want" ]; then
            echo "PASS  $name -> $actual"
            return 0
        fi
    done
    failures=$((failures + 1))
    echo "FAIL  $name -> $actual (expected $expected)"
}

echo "Smoke check against $BASE_URL"

health="$(status_of GET /healthz)"
check '/healthz' '200' "$health"
if [ "$health" = "200" ] && ! grep -q '"database"[[:space:]]*:[[:space:]]*"ok"' "$body_file"; then
    failures=$((failures + 1))
    echo 'FAIL  /healthz did not report database ok'
fi

check '/api/auth/me/ without token' '401' "$(status_of GET /api/auth/me/)"

login_status="$(status_of POST /api/auth/login/ "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")"
check "/api/auth/login/ as $USERNAME" '200' "$login_status"

token=""
refresh=""
if [ "$login_status" = "200" ]; then
    token="$(json_field access)"
    refresh="$(json_field refresh)"
    if [ -z "$token" ]; then
        failures=$((failures + 1))
        echo 'FAIL  login returned no access token'
    fi
fi

if [ -n "$token" ]; then
    me_status="$(status_of GET /api/auth/me/ '' "$token")"
    check '/api/auth/me/' '200' "$me_status"
    if [ "$me_status" = "200" ]; then
        echo "      role: $(json_field role)"
    fi

    check '/api/opportunities/' '200' "$(status_of GET /api/opportunities/ '' "$token")"
    # Knowledge documents are open to the business admin role only; both answers
    # prove the route is wired, so accept either.
    check '/api/knowledge/documents/' '200 403' \
        "$(status_of GET /api/knowledge/documents/ '' "$token")"

    if [ -n "$refresh" ]; then
        check '/api/auth/logout/' '204' \
            "$(status_of POST /api/auth/logout/ "{\"refresh\":\"$refresh\"}" "$token")"
        check '/api/auth/refresh/ after logout' '401' \
            "$(status_of POST /api/auth/refresh/ "{\"refresh\":\"$refresh\"}")"
    fi
fi

if [ "$failures" -gt 0 ]; then
    echo
    echo "SMOKE FAILED: $failures check(s)"
    exit 1
fi
echo
echo 'SMOKE PASSED'
