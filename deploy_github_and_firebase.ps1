$ErrorActionPreference = "Stop"
Set-Location "d:\GS\ANTI\APP\vbee_studio"

$gh = "C:\Program Files\GitHub CLI\gh.exe"
$git = "C:\Program Files\Git\cmd\git.exe"
$firebase = "C:\Users\PC\AppData\Roaming\npm\firebase.cmd"

Write-Host "=== 1. Xác Thực Bảo Mật OAuth 2.0 Device Flow Với GitHub ===" -ForegroundColor Cyan
& $gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Đang mở trang xác thực OAuth 2.0 chính thức của GitHub trên trình duyệt (Không lộ mật khẩu/token)..." -ForegroundColor Yellow
    & $gh auth login --hostname github.com --git-protocol https --web
}

Write-Host "=== 2. Tạo & Đẩy Kho Mã Nguồn Lên GitHub (vnievoices-app) ===" -ForegroundColor Cyan
$repoExists = $false
& $gh repo view vnievoices-app 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { $repoExists = $true }

if (-not $repoExists) {
    & $gh repo create vnievoices-app --public --source=. --remote=origin --push
} else {
    $ghUser = (& $gh api user --jq .login).Trim()
    & $git remote remove origin 2>$null
    & $git remote add origin "https://github.com/$ghUser/vnievoices-app.git"
    & $gh auth setup-git
    & $git push -u origin main --force
}

Write-Host "=== 3. Xác Thực Bảo Mật OAuth 2.0 Với Firebase ===" -ForegroundColor Cyan
$fbLogin = & $firebase login:list 2>&1 | Out-String
if ($fbLogin -match "No authorized accounts") {
    Write-Host "Đang mở trang xác thực Google OAuth cho Firebase..." -ForegroundColor Yellow
    & $firebase login
}

Write-Host "=== 4. Triển Khai VnieVoices App Lên Firebase Hosting ===" -ForegroundColor Cyan
& $firebase deploy --only hosting

Write-Host "=== HOÀN TẤT 100%: Đã đẩy VnieVoices App lên GitHub & Firebase! ===" -ForegroundColor Green
