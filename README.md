# Network-combiner

Network Combiner is a Windows desktop GUI for `go-dispatch-proxy`. It lets you combine multiple active network adapters behind one local SOCKS5 endpoint, assign traffic weights per adapter, and optionally auto-route compatible system traffic through a PAC file.

## What this tool does

- Discovers non-loopback IPv4 addresses from your Windows adapters.
- Lets you choose which adapter IPs are used for outbound proxy traffic.
- Lets you set per-adapter weights (`ratio`) for weighted balancing.
- Starts a local SOCKS5 listener on your chosen port.
- Optionally applies Windows user-level auto-routing with a PAC file.
- Monitors proxy output and auto-fails over away from repeatedly failing adapters.

## How it works (high level)

1. You select one or more adapter IPs and set each adapter's ratio.
2. The app launches `go-dispatch-proxy.exe` with your selected values.
3. A SOCKS5 proxy listens on `127.0.0.1:<port>`.
4. If auto-route is enabled, the app writes a PAC file and sets Windows Internet Settings for the current user to route compatible traffic to that SOCKS5 endpoint.
5. If repeated bind failures are detected for a selected adapter, the app excludes that adapter and restarts the proxy automatically (if at least one other adapter remains active).

## Requirements

- Windows (the GUI and proxy settings integration are Windows-specific).
- Python 3.9+ (Tkinter included in standard Python installation).
- `go-dispatch-proxy.exe` in the same directory as `network-combiner.py`.
- At least one active network adapter with a non-loopback IPv4 address.

## Repository layout

- `network-combiner.py` - Tkinter GUI app.
- `go-dispatch-proxy.exe` - external executable used by the GUI (you provide this file).
- `README.md` - documentation.

## Setup

1. Place `go-dispatch-proxy.exe` in the project folder, next to `network-combiner.py`.
2. Open PowerShell in this folder.
3. Run:

	 `python .\network-combiner.py`

If Python is installed as `py`, you can also run:

`py .\network-combiner.py`

## Step-by-step usage

1. Click **Refresh IPs** to load currently available adapter IPv4 addresses.
2. Check the adapters you want to include.
3. Set a **Ratio** (1-10) for each selected adapter:
	 - `1` means baseline share.
	 - Higher values send proportionally more traffic through that adapter.
4. Set **SOCKS5 Listen Port** (default `8080`).
5. Keep or clear **Auto-route system traffic (PAC + SOCKS5)** depending on your needs.
6. Click **Start Proxy**.
7. Watch the log panel for runtime status.
8. Click **Stop Proxy** when done.

## Weighted ratio example

If you select:

- Adapter A at ratio `1`
- Adapter B at ratio `3`

Adapter B should receive about 3x the traffic share of Adapter A over time.

## Auto-routing behavior

When enabled, the app:

- Creates a PAC file in your temp directory.
- Updates current-user Internet Settings keys under:
	- `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`
- Sets `AutoConfigURL` to the PAC file and disables direct static proxy fields.
- Triggers WinINet settings refresh so compatible apps pick changes up.

On normal stop/exit, it attempts to restore your previous settings and remove the PAC file.

Important notes:

- Routing applies mainly to applications that honor Windows proxy/PAC settings.
- Some apps (or services) ignore WinINet/WinHTTP user proxy settings and will not be affected.
- Proxy changes are user-session scoped, not machine-wide admin policy changes.

## Adapter failover behavior

The app watches proxy output for bind-related failures per source IP.

- Failure threshold is currently `3` events per adapter IP.
- After threshold is reached:
	- That adapter IP is excluded.
	- The proxy process is restarted with remaining active adapters.
- If only one adapter is left, automatic fallback is not performed.

This helps maintain uptime when one network path becomes unusable.

## Troubleshooting

### No IPs are listed

- Ensure adapters are connected and have IPv4 addresses.
- Click **Refresh IPs** after network changes.
- Confirm `ipconfig` output contains non-loopback IPv4 entries.

### Start fails immediately

- Verify `go-dispatch-proxy.exe` exists in the same folder.
- Ensure listen port is valid (`1-65535`) and not already in use.
- Check antivirus or endpoint policy is not blocking process launch.

### Auto-route failed

- Make sure the app runs in the same user session where settings should apply.
- Check that user registry Internet Settings are writable.
- Try disabling auto-route and verify proxy startup separately.

### Traffic is not routed through proxy

- Confirm client app supports SOCKS5 or Windows proxy/PAC.
- If using app-level proxy config, set SOCKS5 to `127.0.0.1:<port>`.
- For PAC mode, reopen or restart apps that cache proxy config.

### Settings were not restored after a crash

- Reopen Network Combiner and stop it cleanly if possible.
- Or manually reset Windows proxy settings in Internet Options / Settings.

## Safety and operational notes

- This tool modifies current-user proxy settings only when auto-route is enabled.
- Abrupt termination (kill process, power loss) can leave temporary proxy settings behind until manually restored.
- Use only trusted binaries for `go-dispatch-proxy.exe`.
- Review local policy requirements before routing enterprise traffic through combined links.

## Known limitations

- Windows-only GUI and proxy setting integration.
- IPv4-focused adapter detection (non-loopback addresses).
- Ratio range is fixed to 1-10 in the GUI.
- Failover threshold is currently fixed in code (not yet configurable from UI).

## Quick checklist before production use

- Validate each adapter's baseline connectivity.
- Choose ratios based on real bandwidth and stability.
- Confirm required business apps honor proxy/PAC.
- Test failover by disabling one adapter during runtime.
- Verify proxy settings restoration path in your environment.

## Acknowledgments

Special thanks to the creator and contributors of go-dispatch-proxy:
https://github.com/extremecoders-re/go-dispatch-proxy

## License

See `LICENSE`.
