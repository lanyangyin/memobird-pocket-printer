$ErrorActionPreference = 'Continue'
$git = 'C:\Program Files\Git\bin\git.exe'
$wd = 'C:\Users\18898\PycharmProjects\apk-re-yddyj'
Set-Location $wd
$env:GIT_SSH_COMMAND = 'ssh -o HostName=20.205.243.166 -o Port=22 -o User=git -o BatchMode=yes -o StrictHostKeyChecking=accept-new'

& $git add -A
$staged = & $git -c core.quotepath=false status --short
$staged

$msg = @'
fix(web): 兼容 Chrome 新版 GATT API，修 GT1 连接报 s.characteristics is not iterable

根因：Chrome 已移除 BluetoothRemoteGATTService.characteristics 同步属性，
只能 await service.getCharacteristics()。GT1 实测直接崩在选特征值这步。

- 新增 web/ble-util.js：选特征值/回包解析/GATT 表，两种 API 都兼容，
  getCharacteristics() 抛错时跳过该服务；服务列表不足时逐个补问已知 UUID
- 修 byUuid() 返回 {service,chr} 包装而非特征值本身（单测抓到）
- tests/test_ble_util.js：17 项（新旧 API、抛错、自定义 UUID、ISSC 兜底、parseFrame）
- tests/test_static_page.py：增加浏览器内 pickWrite 回归（共 22 项）
- notify 日志显示校验和是否通过
'@
& $git commit -q -m $msg

$pushed = $false
for ($i = 1; $i -le 3; $i++) {
    $out = & $git push 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pushed = $true
        Write-Output 'PUSH OK'
        $out | Select-Object -Last 2
        break
    }
    Write-Output ('retry ' + $i)
    $out | Select-Object -Last 1
    Start-Sleep -Seconds 5
}
if (-not $pushed) { Write-Output 'PUSH FAIL' }
& $git --no-pager log --oneline -1
