"""用 UI Automation 操作 Chrome 的蓝牙设备选择弹窗（点不到的原生 UI）。

    python tools/_bt_chooser.py dump        # 列出弹窗元素
    python tools/_bt_chooser.py pick GT1    # 选中并点「配对」
"""
import subprocess
import sys

TITLE = "口袋打印机"

PS_TEMPLATE = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$top = $root.FindAll([System.Windows.Automation.TreeScope]::Children,
    [System.Windows.Automation.Condition]::TrueCondition)
$win = $null
foreach ($w in $top) {
    $n = $w.Current.Name
    if ($n -and $n.Contains('__TITLE__')) { $win = $w; break }
}
if (-not $win) { "NO_WINDOW"; exit 1 }

__ACTION__
"""

DUMP_ACTION = r"""
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
foreach ($e in $all) {
    $c = $e.Current
    if ($c.Name -and ($c.ControlType.ProgrammaticName -match 'DataItem|Button')) {
        $r = $c.BoundingRectangle
        "[" + $c.ControlType.ProgrammaticName.Replace('ControlType.','') + "] '" + $c.Name +
            "' @ " + [int]$r.X + "," + [int]$r.Y
    }
}
"""

PICK_ACTION = r"""
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
$target = $null
foreach ($e in $all) {
    $c = $e.Current
    if ($c.ControlType.ProgrammaticName -eq 'ControlType.DataItem' -and $c.Name -like '*__DEVICE__*') {
        $target = $e; break
    }
}
if (-not $target) { "NO_DEVICE"; exit 2 }
"  找到设备项: " + $target.Current.Name
try {
    $sel = $target.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
    $sel.Select()
    "  已选中"
} catch { "  选择失败: " + $_.Exception.Message }
Start-Sleep -Milliseconds 600

# 反查「配对」按钮（每次重新找，UI 可能重排）
$all2 = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
$btn = $null
foreach ($e in $all2) {
    $c = $e.Current
    if ($c.ControlType.ProgrammaticName -eq 'ControlType.Button' -and
        ($c.Name -eq '配对' -or $c.Name -eq 'Pair')) {
        $btn = $e; break
    }
}
if (-not $btn) { "NO_PAIR_BUTTON"; exit 3 }
try {
    $inv = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $inv.Invoke()
    "  已点「配对」"
} catch { "  配对失败: " + $_.Exception.Message }
"""


def run(action: str) -> int:
    script = PS_TEMPLATE.replace("__TITLE__", TITLE).replace("__ACTION__", action)
    p = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    print(out.rstrip())
    return p.returncode


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dump"
    if cmd == "dump":
        sys.exit(run(DUMP_ACTION))
    if cmd == "pick":
        dev = sys.argv[2] if len(sys.argv) > 2 else "GT1"
        sys.exit(run(PICK_ACTION.replace("__DEVICE__", dev)))
    raise SystemExit(__doc__)
