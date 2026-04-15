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
        self.root.geometry("940x760")
        self.root.minsize(860, 680)
        self.root.resizable(True, True)
        self.root.configure(bg="#0c111b")

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

        self.adapter_count_var = tk.StringVar(value="0 adapters detected")
        self.port_var = tk.StringVar(value="8080")
        self.auto_route_var = tk.BooleanVar(value=True)

        self._build_ui()

        self.selected_vars = {}
        self.ratio_vars = {}
        self.adapter_by_ip = {}

        self.refresh_ips()  # initial load
        self._set_proxy_state(False)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        # Bold dark-glass style optimized for dense network controls.
        self.main_canvas = tk.Canvas(
            self.root,
            bg="#0c111b",
            highlightthickness=0,
            bd=0,
        )
        self.main_canvas.pack(side="left", fill="both", expand=True)
        self.main_scrollbar = tk.Scrollbar(
            self.root, orient="vertical", command=self.main_canvas.yview
        )
        self.main_scrollbar.pack(side="right", fill="y")
        self.main_canvas.configure(yscrollcommand=self.main_scrollbar.set)

        self.main_frame = tk.Frame(self.main_canvas, bg="#0c111b")
        self.main_window = self.main_canvas.create_window(
            (0, 0), window=self.main_frame, anchor="nw"
        )
        self.main_frame.bind("<Configure>", self._on_main_frame_configure)
        self.main_canvas.bind("<Configure>", self._on_main_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.root.bind("<Configure>", self._on_root_resize)

        shell = tk.Frame(self.main_frame, bg="#0c111b")
        shell.pack(fill="both", expand=True, padx=20, pady=18)

        header = tk.Frame(
            shell, bg="#13243d", highlightbackground="#2f4f74", highlightthickness=1
        )
        header.pack(fill="x", pady=(0, 14))

        tk.Label(
            header,
            text="Network Combiner",
            bg="#13243d",
            fg="#e8f2ff",
            font=("Bahnschrift SemiBold", 22),
        ).pack(anchor="w", padx=18, pady=(14, 2))
        tk.Label(
            header,
            text="Combine multiple adapter IPs into one SOCKS5 endpoint with weighted balancing",
            bg="#13243d",
            fg="#9fb5cf",
            font=("Cascadia Mono", 10),
        ).pack(anchor="w", padx=18, pady=(0, 12))

        controls = tk.Frame(
            shell, bg="#152033", highlightbackground="#2b3d5c", highlightthickness=1
        )
        controls.pack(fill="x", pady=(0, 10))

        tk.Button(
            controls,
            text="Refresh Adapters",
            command=self.refresh_ips,
            width=16,
            bg="#285f9a",
            fg="#ffffff",
            activebackground="#3676b8",
            activeforeground="#ffffff",
            relief="flat",
            font=("Bahnschrift SemiBold", 10),
            cursor="hand2",
        ).pack(side="left", padx=(14, 12), pady=12)

        tk.Label(
            controls,
            textvariable=self.adapter_count_var,
            bg="#152033",
            fg="#9fb5cf",
            font=("Cascadia Mono", 10),
        ).pack(side="left", pady=12)

        tk.Label(
            controls,
            text="SOCKS5 Port",
            bg="#152033",
            fg="#e2ecf9",
            font=("Bahnschrift", 10),
        ).pack(side="left", padx=(26, 8), pady=12)

        tk.Entry(
            controls,
            textvariable=self.port_var,
            width=8,
            justify="center",
            bg="#e4edf8",
            fg="#152033",
            relief="flat",
            font=("Cascadia Mono", 10),
        ).pack(side="left", pady=12)

        self.status_label = tk.Label(
            controls,
            text="Proxy Stopped",
            bg="#4e2025",
            fg="#ffd5d9",
            padx=10,
            pady=5,
            font=("Bahnschrift SemiBold", 9),
        )
        self.status_label.pack(side="right", padx=(0, 14), pady=10)

        self.splitter = ttk.Panedwindow(shell, orient="vertical")
        self.splitter.pack(fill="both", expand=True, pady=(0, 10))

        adapter_panel = tk.Frame(
            self.splitter,
            bg="#0f1828",
            highlightbackground="#2b3d5c",
            highlightthickness=1,
        )
        self.adapter_panel = adapter_panel

        top_row = tk.Frame(adapter_panel, bg="#0f1828")
        top_row.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(
            top_row,
            text="Available Adapter IPv4 Addresses",
            bg="#0f1828",
            fg="#e8f2ff",
            font=("Bahnschrift SemiBold", 13),
        ).pack(side="left")

        self.ip_frame = tk.Frame(adapter_panel, bg="#0f1828")
        self.ip_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        control_panel = tk.Frame(
            self.splitter,
            bg="#0c111b",
            highlightbackground="#2b3d5c",
            highlightthickness=1,
        )

        action_row = tk.Frame(control_panel, bg="#0c111b")
        action_row.pack(fill="x", padx=14, pady=(12, 8))

        self.auto_route_cb = tk.Checkbutton(
            action_row,
            text="Auto-route system traffic (PAC + SOCKS5)",
            variable=self.auto_route_var,
            bg="#0c111b",
            fg="#dbe7f7",
            selectcolor="#0c111b",
            activebackground="#0c111b",
            activeforeground="#dbe7f7",
            font=("Bahnschrift", 10),
            anchor="w",
        )
        self.auto_route_cb.pack(side="left")

        btn_frame = tk.Frame(control_panel, bg="#0c111b")
        btn_frame.pack(fill="x", padx=14, pady=(0, 12))

        self.start_btn = tk.Button(
            btn_frame,
            text="Start Proxy",
            bg="#178f62",
            fg="#ffffff",
            activebackground="#1cae77",
            activeforeground="#ffffff",
            relief="flat",
            font=("Bahnschrift SemiBold", 11),
            width=16,
            command=self.start_proxy,
            cursor="hand2",
        )
        self.start_btn.pack(side="left", padx=(0, 10))

        self.stop_btn = tk.Button(
            btn_frame,
            text="Stop Proxy",
            bg="#9b2934",
            fg="#ffffff",
            activebackground="#bb3744",
            activeforeground="#ffffff",
            relief="flat",
            font=("Bahnschrift SemiBold", 11),
            width=16,
            command=self.stop_proxy,
            state="disabled",
            cursor="hand2",
        )
        self.stop_btn.pack(side="left")

        log_panel = tk.Frame(
            self.splitter,
            bg="#111827",
            highlightbackground="#2b3d5c",
            highlightthickness=1,
        )
        self.log_panel = log_panel

        tk.Label(
            log_panel,
            text="Runtime Log",
            bg="#111827",
            fg="#dfe9f8",
            font=("Bahnschrift SemiBold", 12),
        ).pack(anchor="w", padx=14, pady=(10, 6))

        self.log_text = tk.Text(
            log_panel,
            height=12,
            bg="#0a1322",
            fg="#b8d5ff",
            insertbackground="#b8d5ff",
            state="disabled",
            font=("Cascadia Mono", 9),
            relief="flat",
            padx=10,
            pady=8,
        )
        self.log_text.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.splitter.add(adapter_panel, weight=3)
        self.splitter.add(control_panel, weight=0)
        self.splitter.add(log_panel, weight=2)

        self._update_responsive_heights()

    def _set_proxy_state(self, is_running):
        if is_running:
            self.status_label.config(text="Proxy Running", bg="#145a43", fg="#d5ffe8")
        else:
            self.status_label.config(text="Proxy Stopped", bg="#4e2025", fg="#ffd5d9")

    def _on_main_frame_configure(self, _event):
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _on_main_canvas_configure(self, event):
        self.main_canvas.itemconfigure(self.main_window, width=event.width)

    def _on_mousewheel(self, event):
        delta = event.delta
        if delta == 0:
            return

        steps = int(-1 * (delta / 120))
        if steps == 0:
            steps = -1 if delta > 0 else 1

        self.main_canvas.yview_scroll(steps, "units")

    def _widget_is_descendant(self, widget, ancestor):
        current = widget
        while current is not None:
            if current == ancestor:
                return True
            parent_name = current.winfo_parent()
            if not parent_name:
                break
            try:
                current = current.nametowidget(parent_name)
            except Exception:
                break
        return False

    def _on_root_resize(self, _event):
        self._update_responsive_heights()

    def _update_responsive_heights(self):
        window_height = self.root.winfo_height()
        if window_height <= 1:
            return

        available_height = max(320, window_height - 310)
        adapter_height = max(220, int(available_height * 0.53))
        control_height = 92
        log_height_lines = max(8, min(18, int(available_height / 32)))

        self.log_text.config(height=log_height_lines)

        if hasattr(self, "splitter"):
            try:
                self.splitter.sashpos(0, adapter_height)
                self.splitter.sashpos(1, adapter_height + control_height)
            except Exception:
                pass

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
                self.adapter_count_var.set("0 adapters detected")
                self.log(
                    "⚠️ No network IPs found. Connect your networks and click Refresh."
                )
                return

            self.log(f"✅ Found {len(entries)} adapter IPs")
            self.adapter_count_var.set(f"{len(entries)} adapters detected")

            for adapter_name, ip in entries:
                row = tk.Frame(
                    self.ip_frame,
                    bg="#132137",
                    highlightbackground="#2f4a70",
                    highlightthickness=1,
                )
                row.pack(fill="x", pady=4, padx=2)

                # Checkbox
                sel_var = tk.BooleanVar(value=False)
                self.selected_vars[ip] = sel_var
                self.adapter_by_ip[ip] = adapter_name
                cb = tk.Checkbutton(
                    row,
                    text=f"{adapter_name} ({ip})",
                    variable=sel_var,
                    bg="#132137",
                    fg="#e1ecfb",
                    selectcolor="#132137",
                    activebackground="#132137",
                    activeforeground="#e1ecfb",
                    font=("Bahnschrift", 10),
                    anchor="w",
                )
                cb.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=6)

                # Ratio slider
                tk.Label(
                    row,
                    text="Ratio",
                    bg="#132137",
                    fg="#acc3df",
                    font=("Cascadia Mono", 9),
                ).pack(side="left", padx=(12, 4))
                ratio_var = tk.IntVar(value=1)
                self.ratio_vars[ip] = ratio_var
                scale = tk.Scale(
                    row,
                    from_=1,
                    to=10,
                    orient="horizontal",
                    variable=ratio_var,
                    length=170,
                    showvalue=True,
                    bg="#132137",
                    fg="#d6e7ff",
                    troughcolor="#2c4669",
                    highlightthickness=0,
                    activebackground="#6bb1ff",
                )
                scale.pack(side="left", padx=(0, 10), pady=2)

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
            self._set_proxy_state(True)

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
                    self._set_proxy_state(False)
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
        self._set_proxy_state(False)
        self.log(f"Proxy stopped (exit code: {exit_code})")
        self.failover_in_progress = False
        self.proc = None

    def stop_proxy(self):
        if not self.proc or self.proc.poll() is not None:
            self.log("Proxy is not running")
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self._set_proxy_state(False)
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
        try:
            self.root.unbind_all("<MouseWheel>")
        except Exception:
            pass

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
