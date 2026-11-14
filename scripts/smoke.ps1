<#
.SYNOPSIS
Read-only smoke check for a deployed SalesMind AI instance.

.DESCRIPTION
Answers the only question that matters after a deploy: is this instance
actually serving the business API, or merely answering /healthz?

It never writes data and never prints a token or password. Exit code 1 means at
least one check failed.

.EXAMPLE
$env:SMOKE_USERNAME = 'admin'
$env:SMOKE_PASSWORD = '...'
powershell -NoProfile -File scripts/smoke.ps1

.EXAMPLE
$env:SMOKE_BASE_URL = 'http://salesmind.internal:8080'
#>
param(
    [string] $BaseUrl = $env:SMOKE_BASE_URL,
    [string] $Username = $env:SMOKE_USERNAME,
    [string] $Password = $env:SMOKE_PASSWORD,
    # Probing a container name (http://nginx) sends Host: nginx, which
    # ALLOWED_HOSTS rejects. Set this to the hostname users actually type.
    [string] $SmokeHost = $env:SMOKE_HOST
)

$ErrorActionPreference = 'Stop'

if (-not $BaseUrl) { $BaseUrl = 'http://127.0.0.1:8080' }
$BaseUrl = $BaseUrl.TrimEnd('/')
if (-not $Username -or -not $Password) {
    throw 'Set SMOKE_USERNAME and SMOKE_PASSWORD before running the smoke check.'
}

$script:failures = 0

function Invoke-Check {
    param([string] $Method, [string] $Path, [object] $Body, [string] $Token)

    $headers = @{}
    if ($SmokeHost) { $headers['Host'] = $SmokeHost }
    if ($Token) { $headers['Authorization'] = "Bearer $Token" }
    $params = @{
        Uri = "$BaseUrl$Path"
        Method = $Method
        Headers = $headers
        UseBasicParsing = $true
        TimeoutSec = 20
    }
    if ($null -ne $Body) {
        $params['Body'] = ($Body | ConvertTo-Json -Compress)
        $params['ContentType'] = 'application/json'
    }
    try {
        $response = Invoke-WebRequest @params
        return [pscustomobject]@{ Status = [int] $response.StatusCode; Content = $response.Content }
    }
    catch {
        $status = 0
        if ($_.Exception.Response) { $status = [int] $_.Exception.Response.StatusCode }
        return [pscustomobject]@{ Status = $status; Content = '' }
    }
}

function Assert-Status {
    param([string] $Name, [int[]] $Expected, $Result)

    if ($Expected -contains $Result.Status) {
        Write-Output ("PASS  {0} -> {1}" -f $Name, $Result.Status)
        return
    }
    $script:failures++
    Write-Output ("FAIL  {0} -> {1} (expected {2})" -f $Name, $Result.Status, ($Expected -join '/'))
}

Write-Output "Smoke check against $BaseUrl"

$health = Invoke-Check 'GET' '/healthz' $null $null
Assert-Status '/healthz' @(200) $health
if ($health.Status -eq 200 -and $health.Content -notmatch '"database"\s*:\s*"ok"') {
    $script:failures++
    Write-Output 'FAIL  /healthz did not report database ok'
}

$anonymous = Invoke-Check 'GET' '/api/auth/me/' $null $null
Assert-Status '/api/auth/me/ without token' @(401) $anonymous

$login = Invoke-Check 'POST' '/api/auth/login/' @{ username = $Username; password = $Password } $null
Assert-Status "/api/auth/login/ as $Username" @(200) $login

$token = ''
if ($login.Status -eq 200) {
    $token = ($login.Content | ConvertFrom-Json).access
    if (-not $token) {
        $script:failures++
        Write-Output 'FAIL  login returned no access token'
    }
}

if ($token) {
    $me = Invoke-Check 'GET' '/api/auth/me/' $null $token
    Assert-Status '/api/auth/me/' @(200) $me
    if ($me.Status -eq 200) {
        $role = ($me.Content | ConvertFrom-Json).role
        Write-Output "      role: $role"
    }

    Assert-Status '/api/opportunities/' @(200) (Invoke-Check 'GET' '/api/opportunities/' $null $token)

    # Knowledge documents are open to the business admin role only; both
    # answers prove the route is wired, so accept either.
    Assert-Status '/api/knowledge/documents/' @(200, 403) (Invoke-Check 'GET' '/api/knowledge/documents/' $null $token)

    $refresh = ($login.Content | ConvertFrom-Json).refresh
    if ($refresh) {
        Assert-Status '/api/auth/logout/' @(204) (Invoke-Check 'POST' '/api/auth/logout/' @{ refresh = $refresh } $token)
        Assert-Status '/api/auth/refresh/ after logout' @(401) (Invoke-Check 'POST' '/api/auth/refresh/' @{ refresh = $refresh } $null)
    }
}

if ($script:failures -gt 0) {
    Write-Output ""
    Write-Output ("SMOKE FAILED: {0} check(s)" -f $script:failures)
    exit 1
}
Write-Output ''
Write-Output 'SMOKE PASSED'
exit 0
