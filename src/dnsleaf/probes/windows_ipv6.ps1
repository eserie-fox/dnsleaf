# Fixed read-only probe for Windows PowerShell 5.1. No operator data is interpolated.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::ASCII
try {
    $adapters = @(Get-NetAdapter -IncludeHidden -ErrorAction Stop)
    $addresses = @(Get-NetIPAddress -AddressFamily IPv6 -PolicyStore ActiveStore -ErrorAction Stop)
    $records = @(
        foreach ($address in $addresses) {
            foreach ($field in @('IPAddress', 'PrefixLength', 'InterfaceIndex', 'InterfaceAlias',
                                 'PrefixOrigin', 'SuffixOrigin', 'AddressState', 'SkipAsSource')) {
                if ($null -eq $address.$field) { throw "Missing address field: $field" }
            }
            if ($address.SkipAsSource -isnot [bool]) { throw 'Invalid SkipAsSource type' }
            $matching = @($adapters | Where-Object { $_.InterfaceIndex -eq $address.InterfaceIndex })
            $mac = $null
            if ($matching.Count -eq 1) { $mac = $matching[0].MacAddress }
            [ordered]@{
                IPAddress = [string]$address.IPAddress
                PrefixLength = [int]$address.PrefixLength
                InterfaceIndex = [int]$address.InterfaceIndex
                InterfaceAlias = [string]$address.InterfaceAlias
                HardwareAddress = $mac
                PrefixOrigin = [string]$address.PrefixOrigin
                SuffixOrigin = [string]$address.SuffixOrigin
                AddressState = [string]$address.AddressState
                SkipAsSource = $address.SkipAsSource
            }
        }
    )
    $json = ConvertTo-Json -InputObject @{ addresses = @($records) } -Depth 4 -Compress
    # ASCII bytes survive QGA Base64 -> PVE decoded strings -> outer JSON unchanged.
    # Escaping each UTF-16 code unit also preserves non-BMP surrogate pairs.
    $ascii = [regex]::Replace($json, '[\u007f-\uffff]', {
        param($match)
        '\u{0:x4}' -f [int][char]$match.Value
    })
    [Console]::WriteLine($ascii)
    exit 0
} catch {
    # No partial inventory is emitted and no unrelated Guest data is dumped.
    [Console]::Error.WriteLine('dnsleaf IPv6 metadata probe failed; check NetTCPIP/NetAdapter CIM access')
    exit 1
}
