@echo off
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$in = [IO.File]::OpenRead('rawnand.bin'); $size = 1073741824; $part = 0; $buf = New-Object byte[] $size; while (($read = $in.Read($buf, 0, $size)) -gt 0) { $name = 'rawnand.bin.{0:D2}' -f $part; $out = [IO.File]::OpenWrite($name); $out.Write($buf, 0, $read); $out.Close(); Write-Host ('Written ' + $name); $part++ }; $in.Close(); Write-Host 'Done.'"
