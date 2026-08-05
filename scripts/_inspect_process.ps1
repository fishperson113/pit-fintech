$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'promote-gold|build-gold|run_t4' }
if ($procs) {
    foreach ($p in $procs) {
        $cpu = $null
        try { $cpu = (Get-Process -Id $p.ProcessId -ErrorAction Stop).CPU } catch {}
        $ws = [math]::Round($p.WorkingSetSize / 1MB, 1)
        [PSCustomObject]@{
            PID = $p.ProcessId
            Name = $p.Name
            Created = $p.CreationDate
            WorkingSetMB = $ws
            CPUSeconds = $cpu
            CommandLine = $p.CommandLine
        } | Format-List
    }
} else {
    Write-Output "NO_MATCHING_PROCESS"
}
