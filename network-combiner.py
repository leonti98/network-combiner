import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import re
import threading
import os
import ctypes
import winreg
import tempfile


class NetworkCombinerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Network Combiner - go-dispatch-proxy GUI")
        self.root.geometry("680x620")
        self.root.resizable(True, True)

        self.exe_path = "go-dispatch-proxy.exe"  # must be in the same folder
        self.proc = None
        self.system_proxy_backup = None
        self.system_proxy_applied = False
        self.pac_file_path = None
        self.current_adapter_specs = {}
        self.excluded_failed_ips = set()
        self.adapter_fail_counts = {}
        self.failure_threshold = 3
        self.internal_restart_pending = False
        self.failover_in_progress = False
        self.bind_error_pattern = re.compile(
            r"dial\s+tcp4\s+(\d+\.\d+\.\d+\.\d+):\d+->.*bind:",
            flags=re.IGNORECASE,
        )

        # Title
        tk.Label(
            self.root, text="Combine Multiple Networks", font=("Arial", 16, "bold")
        ).pack(pady=10)
        tk.Label(
            self.root, text="Select IPs and set ratios → Start", font=("Arial", 10)
        ).pack()

        # IP list area
        tk.Label(
            self.root,
            text="Available IP Addresses (non-loopback IPv4)",
            font=("Arial", 12, "bold"),
        ).pack(pady=(20, 5))

        self.ip_frame = tk.Frame(self.root)
        self.ip_frame.pack(fill="both", expand=True, padx=20)

        btn_frame_top = tk.Frame(self.root)
        btn_frame_top.pack(pady=8)
        tk.Button(
            btn_frame_top, text="🔄 Refresh IPs", command=self.refresh_ips, width=15
        ).pack(side="left", padx=5)

        # Listen port
        port_frame = tk.Frame(self.root)
        port_frame.pack(pady=8)
        tk.Label(port_frame, text="SOCKS5 Listen Port:").pack(side="left")
        self.port_var = tk.StringVar(value="8080")
        tk.Entry(port_frame, textvariable=self.port_var, width=8).pack(
            side="left", padx=5
        )

        # Optional system-level auto-routing (WinINet apps)
        auto_route_frame = tk.Frame(self.root)
        auto_route_frame.pack(pady=(0, 8))
        self.auto_route_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            auto_route_frame,
            text="Auto-route system traffic (PAC + SOCKS5)",
            variable=self.auto_route_var,
            anchor="w",
        ).pack(side="left")

        # Action buttons
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)
        self.start_btn = tk.Button(
            btn_frame,
            text="▶️ Start Proxy",
            bg="#00c853",
            fg="white",
            font=("Arial", 10, "bold"),
            width=15,
            command=self.start_proxy,
        )
        self.start_btn.pack(side="left", padx=10)

        self.stop_btn = tk.Button(
            btn_frame,
            text="⏹️ Stop Proxy",
            bg="#d50000",
            fg="white",
            font=("Arial", 10, "bold"),
            width=15,
            command=self.stop_proxy,
            state="disabled",
        )
        self.stop_btn.pack(side="left", padx=10)

        # Log
        tk.Label(self.root, text="Log / Status:", anchor="w").pack(fill="x", padx=20)
        self.log_text = tk.Text(
            self.root, height=12, bg="#f0f0f0", state="disabled", font=("Consolas", 9)
        )
        self.log_text.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.selected_vars = {}
        self.ratio_vars = {}
        self.adapter_by_ip = {}

        self.refresh_ips()  # initial load

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def refresh_ips(self):
        # Clear old widgets
        for widget in self.ip_frame.winfo_children():
            widget.destroy()
        self.selected_vars.clear()
        self.ratio_vars.clear()
        self.adapter_by_ip.clear()

        try:
            output = subprocess.check_output(["ipconfig"], shell=True, text=True)
            entries = self._extract_adapter_ips(output)

            if not entries:
                self.log(
                    "⚠️ No network IPs found. Connect your networks and click Refresh."
                )
                return

            self.log(f"✅ Found {len(entries)} adapter IPs")

            for adapter_name, ip in entries:
                row = tk.Frame(self.ip_frame)
                row.pack(fill="x", pady=3)

                # Checkbox
                sel_var = tk.BooleanVar(value=False)
                self.selected_vars[ip] = sel_var
                self.adapter_by_ip[ip] = adapter_name
                cb = tk.Checkbutton(
                    row,
                    text=f"{adapter_name} ({ip})",
                    variable=sel_var,
                    anchor="w",
                )
                cb.pack(side="left", padx=5)

                # Ratio slider
                tk.Label(row, text="Ratio:").pack(side="left", padx=(20, 5))
                ratio_var = tk.IntVar(value=1)
                self.ratio_vars[ip] = ratio_var
                scale = tk.Scale(
                    row,
                    from_=1,
                    to=10,
                    orient="horizontal",
                    variable=ratio_var,
                    length=180,
                    showvalue=True,
                )
                scale.pack(side="left")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to get IPs:\n{str(e)}")

    def _extract_adapter_ips(self, ipconfig_output):
        entries = []
        seen_ips = set()
        current_adapter = "Unknown"

        for raw_line in ipconfig_output.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()

            if not stripped:
                continue

            # Adapter header lines usually look like: "Ethernet adapter Wi-Fi:"
            if line == stripped and stripped.endswith(":"):
                header = stripped[:-1]
                lower_header = header.lower()
                marker = " adapter "
                if marker in lower_header:
                    idx = lower_header.find(marker)
                    current_adapter = header[idx + len(marker) :].strip()
                else:
                    current_adapter = header
                continue

            ip_match = re.search(
                r"IPv4[^:]*:\s*([\d.]+)", stripped, flags=re.IGNORECASE
            )
            if not ip_match:
                continue

            ip = ip_match.group(1)
            if ip.startswith(("127.", "0.0.0.0")):
                continue
            if ip in seen_ips:
                continue

            seen_ips.add(ip)
            entries.append((current_adapter, ip))

        return entries

    def _build_selected_adapter_specs(self):
        specs = {}
        for ip, var in self.selected_vars.items():
            if var.get():
                specs[ip] = self.ratio_vars[ip].get()
        return specs

    def _build_args_from_specs(self):
        selected_args = []
        for ip, ratio in self.current_adapter_specs.items():
            if ip in self.excluded_failed_ips:
                continue

            if ratio > 1:
                selected_args.append(f"{ip}@{ratio}")
            else:
                selected_args.append(ip)

        return selected_args

    def start_proxy(self):
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("Already running", "Proxy is already active!")
            return

        self.current_adapter_specs = self._build_selected_adapter_specs()
        self.excluded_failed_ips.clear()
        self.adapter_fail_counts.clear()
        self.internal_restart_pending = False
        self.failover_in_progress = False
        self._start_proxy_instance(show_dialog_on_empty=True, is_failover_restart=False)

    def _start_proxy_instance(
        self, show_dialog_on_empty=False, is_failover_restart=False
    ):
        selected_args = self._build_args_from_specs()

        if len(selected_args) == 0:
            msg = "No active adapters left for proxy startup."
            self.log(f"⚠️ {msg}")
            if show_dialog_on_empty:
                messagebox.showwarning("Nothing selected", msg)
            return False

        if not is_failover_restart:
            self.log("Selected adapters:")
            for ip, ratio in self.current_adapter_specs.items():
                if ip in self.excluded_failed_ips:
                    continue
                adapter_name = self.adapter_by_ip.get(ip, "Unknown")
                self.log(f"  - {adapter_name} -> {ip} (ratio {ratio})")
        else:
            self.log("🔁 Restarting proxy with fallback adapters:")
            for ip, ratio in self.current_adapter_specs.items():
                if ip in self.excluded_failed_ips:
                    continue
                adapter_name = self.adapter_by_ip.get(ip, "Unknown")
                self.log(f"  - {adapter_name} -> {ip} (ratio {ratio})")

            if self.excluded_failed_ips:
                excluded_names = [
                    f"{self.adapter_by_ip.get(ip, 'Unknown')} ({ip})"
                    for ip in sorted(self.excluded_failed_ips)
                ]
                self.log(f"  Excluded failed adapters: {', '.join(excluded_names)}")

        if self.proc and self.proc.poll() is None:
            self.log("Proxy is already active")
            return False

        if not self.current_adapter_specs:
            messagebox.showwarning(
                "Nothing selected", "Please select at least one IP address."
            )
            return False

        full_cmd = [self.exe_path, "-lport", self.port_var.get()] + selected_args

        self.log(f"🚀 Starting: {' '.join(full_cmd)}")

        try:
            listen_port = int(self.port_var.get())
            if listen_port < 1 or listen_port > 65535:
                raise ValueError("Port must be between 1 and 65535")

            self.proc = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")

            if self.auto_route_var.get():
                ok, err = self._enable_system_proxy(listen_port)
                if not ok:
                    self.log("⚠️ Failed to enable automatic traffic routing")
                    self.log(f"Reason: {err}")
                    messagebox.showerror(
                        "Auto-routing failed",
                        "Proxy started, but traffic routing could not be enabled.\n"
                        "Run as the same user session and ensure system proxy settings are writable.\n\n"
                        f"Details: {err}",
                    )
                    try:
                        self.proc.terminate()
                    except Exception:
                        pass
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self.proc = None
                    return False

                self.log(
                    f"✅ Auto-routing enabled: PAC SOCKS5 -> 127.0.0.1:{listen_port}"
                )
                self.log(
                    "ℹ️ Note: only apps that honor Windows proxy/PAC settings will be routed."
                )

            # Live log reader
            threading.Thread(target=self._read_output, daemon=True).start()
            return True
        except Exception as exc:
            self.log(
                "Failed to start process. Make sure go-dispatch-proxy.exe is in the same folder."
            )
            messagebox.showerror("Start failed", str(exc))
            return False

    def _process_proxy_line(self, text):
        self.log(f"[proxy] {text}")

        match = self.bind_error_pattern.search(text)
        if not match:
            return

        failed_ip = match.group(1)
        if failed_ip not in self.current_adapter_specs:
            return

        fail_count = self.adapter_fail_counts.get(failed_ip, 0) + 1
        self.adapter_fail_counts[failed_ip] = fail_count

        adapter_name = self.adapter_by_ip.get(failed_ip, "Unknown")
        self.log(
            f"⚠️ Detected bind failure on {adapter_name} ({failed_ip}) [{fail_count}/{self.failure_threshold}]"
        )

        if fail_count < self.failure_threshold:
            return

        if failed_ip in self.excluded_failed_ips:
            return

        active_ips = [
            ip
            for ip in self.current_adapter_specs.keys()
            if ip not in self.excluded_failed_ips
        ]
        if len(active_ips) <= 1:
            self.log("⚠️ Fallback not possible: only one active adapter remains.")
            return

        if self.failover_in_progress:
            return

        self.excluded_failed_ips.add(failed_ip)
        self.failover_in_progress = True
        self.internal_restart_pending = True

        self.log(
            f"🔁 Failover triggered: excluding {adapter_name} ({failed_ip}) and restarting proxy."
        )

        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            else:
                self.root.after(0, self._on_process_stopped, 0)
        except Exception as exc:
            self.log(f"⚠️ Failover restart could not stop process cleanly: {exc}")
            self.internal_restart_pending = False
            self.failover_in_progress = False

    def _read_output(self):
        if not self.proc:
            return

        try:
            if self.proc.stdout:
                for line in self.proc.stdout:
                    text = line.strip()
                    if text:
                        self.root.after(0, self._process_proxy_line, text)
        finally:
            if self.proc:
                exit_code = self.proc.wait()
                self.root.after(0, self._on_process_stopped, exit_code)

    def _on_process_stopped(self, exit_code):
        if self.system_proxy_applied and not self.internal_restart_pending:
            restored, err = self._restore_system_proxy()
            if restored:
                self.log("✅ Restored previous system proxy settings")
            else:
                self.log(f"⚠️ Could not restore previous system proxy settings: {err}")

        if self.internal_restart_pending:
            self.log(
                f"Proxy restarting after adapter failover (exit code: {exit_code})"
            )
            self.proc = None
            self.internal_restart_pending = False
            started = self._start_proxy_instance(
                show_dialog_on_empty=False, is_failover_restart=True
            )
            self.failover_in_progress = False
            if started:
                return

        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.log(f"Proxy stopped (exit code: {exit_code})")
        self.failover_in_progress = False
        self.proc = None

    def stop_proxy(self):
        if not self.proc or self.proc.poll() is not None:
            self.log("Proxy is not running")
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.proc = None
            return

        self.log("Stopping proxy...")
        self.internal_restart_pending = False
        self.failover_in_progress = False
        try:
            self.proc.terminate()
        except Exception as exc:
            messagebox.showerror("Stop failed", str(exc))

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno(
                "Exit", "Proxy is still running. Stop it and exit?"
            ):
                return
            try:
                self.proc.terminate()
            except Exception:
                pass

        if self.system_proxy_applied:
            self._restore_system_proxy()

        self.root.destroy()

    def _refresh_internet_settings(self):
        # Notify WinINet clients that proxy settings changed.
        internet_set_option = ctypes.windll.wininet.InternetSetOptionW
        internet_set_option(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
        internet_set_option(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH

    def _read_internet_setting(self, key, name, default=None):
        try:
            value, _ = winreg.QueryValueEx(key, name)
            return value
        except FileNotFoundError:
            return default

    def _enable_system_proxy(self, port):
        settings_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        try:
            self.pac_file_path = self._write_pac_file(port)
            pac_url = self._to_file_uri(self.pac_file_path)

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                settings_path,
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE,
            ) as key:
                if self.system_proxy_backup is None:
                    self.system_proxy_backup = {
                        "ProxyEnable": int(
                            self._read_internet_setting(key, "ProxyEnable", 0)
                        ),
                        "ProxyServer": self._read_internet_setting(
                            key, "ProxyServer", ""
                        ),
                        "ProxyOverride": self._read_internet_setting(
                            key, "ProxyOverride", ""
                        ),
                        "AutoConfigURL": self._read_internet_setting(
                            key, "AutoConfigURL", ""
                        ),
                        "AutoDetect": int(
                            self._read_internet_setting(key, "AutoDetect", 0)
                        ),
                    }

                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
                winreg.SetValueEx(
                    key,
                    "AutoConfigURL",
                    0,
                    winreg.REG_SZ,
                    pac_url,
                )
                winreg.SetValueEx(key, "AutoDetect", 0, winreg.REG_DWORD, 0)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, "")
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "")

            self._refresh_internet_settings()
            self.system_proxy_applied = True
            return True, None
        except Exception as exc:
            return False, str(exc)

    def _restore_system_proxy(self):
        if not self.system_proxy_backup:
            self.system_proxy_applied = False
            return True, None

        settings_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                settings_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key,
                    "ProxyEnable",
                    0,
                    winreg.REG_DWORD,
                    int(self.system_proxy_backup.get("ProxyEnable", 0)),
                )
                winreg.SetValueEx(
                    key,
                    "ProxyServer",
                    0,
                    winreg.REG_SZ,
                    str(self.system_proxy_backup.get("ProxyServer", "")),
                )
                winreg.SetValueEx(
                    key,
                    "ProxyOverride",
                    0,
                    winreg.REG_SZ,
                    str(self.system_proxy_backup.get("ProxyOverride", "")),
                )
                winreg.SetValueEx(
                    key,
                    "AutoConfigURL",
                    0,
                    winreg.REG_SZ,
                    str(self.system_proxy_backup.get("AutoConfigURL", "")),
                )
                winreg.SetValueEx(
                    key,
                    "AutoDetect",
                    0,
                    winreg.REG_DWORD,
                    int(self.system_proxy_backup.get("AutoDetect", 0)),
                )

            self._refresh_internet_settings()
            self._cleanup_pac_file()
            self.system_proxy_applied = False
            return True, None
        except Exception as exc:
            return False, str(exc)

    def _write_pac_file(self, port):
        pac_body = (
            "function FindProxyForURL(url, host) {\n"
            '    if (isPlainHostName(host) || dnsDomainIs(host, "localhost")) {\n'
            '        return "DIRECT";\n'
            "    }\n"
            f'    return "SOCKS5 127.0.0.1:{port}; DIRECT";\n'
            "}\n"
        )

        pac_dir = tempfile.gettempdir()
        pac_path = os.path.join(pac_dir, "network-combiner-proxy.pac")
        with open(pac_path, "w", encoding="utf-8") as pac_file:
            pac_file.write(pac_body)

        return pac_path

    def _cleanup_pac_file(self):
        if not self.pac_file_path:
            return

        try:
            if os.path.exists(self.pac_file_path):
                os.remove(self.pac_file_path)
        except Exception:
            pass
        finally:
            self.pac_file_path = None

    def _to_file_uri(self, path):
        normalized = os.path.abspath(path).replace("\\", "/")
        return f"file:///{normalized}"

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = NetworkCombinerApp()
    app.run()
