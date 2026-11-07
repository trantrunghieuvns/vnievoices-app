$ErrorActionPreference = "Stop"
Set-Location "d:\GS\ANTI\APP\vbee_studio"

$gh = "C:\Program Files\GitHub CLI\gh.exe"
$git = "C:\Program Files\Git\cmd\git.exe"
$firebase = "C:\Users\PC\AppData\Roaming\npm\firebase.cmd"

Write-Host "=== 1. Checking GitHub CLI Authentication ===" -ForegroundColor Cyan
& $gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Opening GitHub Web OAuth Login in your browser..." -ForegroundColor Yellow
    & $gh auth login --hostname github.com --git-protocol https --web
}

Write-Host "=== 2. Creating & Pushing GitHub Repository (vbee-ai-voice-studio) ===" -ForegroundColor Cyan
$repoExists = $false
& $gh repo view vbee-ai-voice-studio 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { $repoExists = $true }

if (-not $repoExists) {
    & $gh repo create vbee-ai-voice-studio --public --source=. --remote=origin --push
} else {
    $ghUser = (& $gh api user --jq .login).Trim()
    & $git remote remove origin 2>$null
    & $git remote add origin "https://github.com/$ghUser/vbee-ai-voice-studio.git"
    & $gh auth setup-git
    & $git push -u origin main --force
}

Write-Host "=== 3. Checking Firebase CLI Authentication ===" -ForegroundColor Cyan
$fbLogin = & $firebase login:list 2>&1 | Out-String
if ($fbLogin -match "No authorized accounts") {
    Write-Host "Opening Firebase Google OAuth Login in your browser..." -ForegroundColor Yellow
    & $firebase login
}

Write-Host "=== 4. Deploying to Firebase Hosting ===" -ForegroundColor Cyan
& $firebase deploy --only hosting

Write-Host "=== DONE: 100% Pushed to GitHub & Firebase! ===" -ForegroundColor Green
