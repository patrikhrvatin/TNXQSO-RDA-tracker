import requests
import time
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
import sys
import os
import csv
import webbrowser
import socketio
from datetime import datetime

# --- POSTAVKE TEMA (Black Night stil) ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# --- POMOĆNA FUNKCIJA ZA IKONU ---
def resource_path(relative_path):
    """ Dobiva apsolutnu putanju do resursa, radi za dev i za PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Postavke
URL_MAIN = "https://tnxqso.com/static/js/activeStations.json"
URL_LOG_BASE = "https://tnxqso.com/"
URL_CSV_DOWNLOAD = "https://cfmrda.ru/aiohttp/download/hunter_rda/9A5CW/csv"
REFRESH_MS = 5000 
CSV_FILENAME = "rda_slots.csv"

def download_latest_rda_csv():
    """ Automatski preuzima najnoviji CSV s linka i sprema ga kao rda_slots.csv """
    try:
        print("Preuzimam najnoviju RDA CSV datoteku...")
        r = requests.get(URL_CSV_DOWNLOAD, timeout=10)
        if r.status_code == 200:
            with open(CSV_FILENAME, "wb") as f:
                f.write(r.content)
            print("CSV datoteka je uspješno preuzeta i spremljena kao rda_slots.csv.")
        else:
            print(f"Greška kod preuzimanja CSV-a. Status kod: {r.status_code}")
    except Exception as e:
        print(f"Nije moguće preuzeti CSV: {e}")

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("TNX Monitor + RDA Cluster Live (Win7 Optimized)")
        self.root.geometry("860x760")
        self.root.minsize(700, 600)
        
        # Učitavanje CSV baze
        self.rda_data_db = {}
        self.load_rda_csv()

        # Spremnici za TNXQSO praćenje i QSY/Log alerte
        self.cluster_spots = [] 
        self.last_data = {}      # Pamti zadnju frekvenciju i rda stanice za QSY alert
        self.last_qso_seen = {}  # Pamti zadnji qso za moj znak
        
        # Kontrolne varijable za filtere
        self.filter_only_new_var = ctk.BooleanVar(value=False)
        self.hide_popup_var = ctk.BooleanVar(value=False)

        # Postavljanje ikone unutar klase
        try:
            self.root.iconbitmap(resource_path('tnxqso2.ico'))
        except:
            pass
        
        # Glavni layout (Grid)
        self.root.rowconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)

        # Stil za Treeview tablice prilagođen za Win7
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", 
                        background="#1a1a1a", 
                        foreground="#ffffff", 
                        fieldbackground="#1a1a1a", 
                        rowheight=24,
                        font=("Arial", 9))
        style.configure("Treeview.Heading", 
                        background="#2b2b2b", 
                        foreground="#ffffff", 
                        font=("Arial", 9, "bold"))
        style.map("Treeview", background=[('selected', '#1f538d')])

        # --- GORNJI DIO: TNXQSO Aktivnost ---
        top_frame = ctk.CTkFrame(root, corner_radius=6)
        top_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        top_frame.rowconfigure(1, weight=1)
        top_frame.columnconfigure(0, weight=1)

        ctk.CTkLabel(top_frame, text="TNXQSO Live Aktivnost stanica", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w", padx=5, pady=2)

        columns_top = ("Call", "Freq", "RDA", "Status Slotova", "LastQSO")
        self.tree_top = ttk.Treeview(top_frame, columns=columns_top, show='headings', height=8)
        
        self.tree_top.heading("Call", text="Pozivni")
        self.tree_top.heading("Freq", text="Freq (kHz)")
        self.tree_top.heading("RDA", text="RDA (Sve reference)")
        self.tree_top.heading("Status Slotova", text="RDA Status / Novi Band?")
        self.tree_top.heading("LastQSO", text="Zadnji QSO")
        
        self.tree_top.column("Call", width=80, anchor="center")
        self.tree_top.column("Freq", width=80, anchor="center")
        self.tree_top.column("RDA", width=130, anchor="center")
        self.tree_top.column("Status Slotova", width=170, anchor="w")
        self.tree_top.column("LastQSO", width=150, anchor="w")
        
        self.tree_top.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.tree_top.bind("<Button-1>", self.on_top_table_click)

        # --- DONJI DIO: RDA Cluster (Zadnjih 30 min) ---
        bottom_frame = ctk.CTkFrame(root, corner_radius=6)
        bottom_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        bottom_frame.rowconfigure(2, weight=1)
        bottom_frame.columnconfigure(0, weight=1)

        ctk.CTkLabel(bottom_frame, text="RDA Cluster - Spotovi (Zadnjih 30 min)", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w", padx=5, pady=2)

        # Kontrole iznad donje tablice
        controls_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        controls_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=2)
        
        chk_filter = ctk.CTkCheckBox(
            controls_frame, 
            text="Prikazi samo nove bandove / oblasti", 
            variable=self.filter_only_new_var, 
            command=self.refresh_bottom_table,
            font=("Arial", 9)
        )
        chk_filter.pack(side=tk.LEFT, padx=5)

        chk_hide_popup = ctk.CTkCheckBox(
            controls_frame, 
            text="Sakrij pop-up alert", 
            variable=self.hide_popup_var,
            font=("Arial", 9)
        )
        chk_hide_popup.pack(side=tk.LEFT, padx=15)

        columns_bot = ("Time", "Call", "Freq", "Band", "Mode", "RDA", "Status / Novi Band")
        self.tree_bot = ttk.Treeview(bottom_frame, columns=columns_bot, show='headings', height=7)
        
        self.tree_bot.heading("Time", text="Vrijeme")
        self.tree_bot.heading("Call", text="Pozivni")
        self.tree_bot.heading("Freq", text="Freq")
        self.tree_bot.heading("Band", text="Band")
        self.tree_bot.heading("Mode", text="Mod")
        self.tree_bot.heading("RDA", text="RDA")
        self.tree_bot.heading("Status / Novi Band", text="Status / Novi Band")

        self.tree_bot.column("Time", width=70, anchor="center")
        self.tree_bot.column("Call", width=80, anchor="center")
        self.tree_bot.column("Freq", width=80, anchor="center")
        self.tree_bot.column("Band", width=50, anchor="center")
        self.tree_bot.column("Mode", width=60, anchor="center")
        self.tree_bot.column("RDA", width=110, anchor="center")
        self.tree_bot.column("Status / Novi Band", width=220, anchor="w")

        self.tree_bot.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        self.tree_bot.bind("<Button-1>", self.on_bottom_table_click)

        # Status bar na dnu
        self.status_bar = ctk.CTkLabel(root, text="...", anchor="w", font=("Arial", 9))
        self.status_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=2)

        # Pokretanje Socket.IO i petlji
        self.init_rdacabinet_socket()
        self.update_loop()

    def load_rda_csv(self):
        """ Učitava CSV u matričnom formatu """
        self.rda_data_db = {}
        if not os.path.exists(CSV_FILENAME):
            print(f"Upozorenje: CSV datoteka '{CSV_FILENAME}' nije pronađena.")
            return
        try:
            with open(CSV_FILENAME, mode='r', encoding='utf-8', errors='ignore') as infile:
                reader = csv.reader(infile)
                header = None
                for row in reader:
                    if not row: continue
                    row_str = " ".join(row).upper()
                    if "RDA" in row_str and ("1.8" in row_str or "3.5" in row_str or "7" in row_str):
                        header = [h.strip('"').strip() for h in row]
                        continue
                    
                    if header and len(row) >= 2:
                        rda_code = ""
                        row_dict = {}
                        for idx, val in enumerate(row):
                            if idx < len(header):
                                col_name = header[idx]
                                clean_val = val.strip('"').strip()
                                row_dict[col_name] = clean_val
                                if col_name.upper() == "RDA":
                                    rda_code = clean_val
                        
                        if not rda_code and len(row) > 1:
                            rda_code = row[1].strip('"').strip()
                        
                        if rda_code and "-" in rda_code:
                            self.rda_data_db[rda_code.upper()] = row_dict
                            
            print(f"Uspješno učitano preko {len(self.rda_data_db)} RDA oblasti iz matričnog CSV-a.")
        except Exception as e:
            print(f"Greška kod čitanja matričnog CSV-a: {e}")

    def get_band_info(self, freq_str):
        """ Vraća CSV ključ opsega i ispravan naziv opsega u metrima """
        try:
            f = float(freq_str)
            if 1800 <= f <= 2000 or 1.8 <= f < 2.0: return "1.8", "160m"
            elif 3500 <= f <= 4000 or 3.5 <= f < 4.0: return "3.5", "80m"
            elif 7000 <= f <= 7300 or 7.0 <= f < 7.3: return "7", "40m"
            elif 10100 <= f <= 10150 or 10.1 <= f <= 10.15: return "10", "30m"
            elif 14000 <= f <= 14350 or 14.0 <= f < 14.35: return "14", "20m"
            elif 18068 <= f <= 18168 or 18.068 <= f < 18.168: return "18", "17m"
            elif 21000 <= f <= 21450 or 21.0 <= f < 21.45: return "21", "15m"
            elif 24890 <= f <= 24990 or 24.89 <= f < 24.99: return "24", "12m"
            elif 28000 <= f <= 29700 or 28.0 <= f < 29.7: return "28", "10m"
        except:
            pass
        return "-", "-"

    def check_slot_status_multi(self, rda_str, band_key, band_name):
        """ Provjerava imamo li već odrađen cijeli band u toj oblasti """
        if not rda_str or rda_str == "-":
            return "Nepoznato", False, False

        rdas = [r.strip().upper() for r in rda_str.split() if r.strip()]
        needed_descs = []
        is_any_new = False
        is_any_all_time = False

        for rda in rdas:
            if rda not in self.rda_data_db:
                needed_descs.append(f"NOVA: {rda}")
                is_any_new = True
                is_any_all_time = True
            else:
                row_data = self.rda_data_db[rda]
                if band_key == "-":
                    continue
                band_val = row_data.get(band_key, "").strip()
                
                if not band_val or band_val == "":
                    needed_descs.append(f"Novi band ({rda} {band_name})")
                    is_any_new = True

        if is_any_new:
            return " | ".join(needed_descs), True, is_any_all_time
        else:
            return f"Vec potvrđeno ({band_name})", False, False

    def init_rdacabinet_socket(self):
        """ Povezivanje na rdacabinet.ru websocket cluster """
        self.sio = socketio.Client()

        @self.sio.event
        def connect():
            print("[USPJESNO] Povezan na rdacabinet.ru cluster!")

        @self.sio.event
        def disconnect():
            print("[PREKID] Veza s rdacabinet.ru prekinuta.")

        @self.sio.on("new_spot")
        def on_new_spot(data):
            if data:
                try:
                    dijelovi = str(data).split("|")
                    time_spot = datetime.now().strftime("%H:%M:%S")
                    call = "???"
                    freq = "-"
                    mode = "DIGI"
                    rda = ""

                    str_data_full = str(data)
                    
                    time_m = re.search(r'\b\d{2}:\d{2}(?::\d{2})?\b', str_data_full)
                    freq_m = re.search(r'\b[1-9]\d{3,4}\.\d\b', str_data_full)
                    rda_matches = re.findall(r'[A-Z]{2}-\d{2,3}', str_data_full)

                    if time_m:
                        time_spot = time_m.group(0)
                    
                    if freq_m:
                        freq = freq_m.group(0)
                    elif len(dijelovi) > 1 and "." in dijelovi[1]:
                        freq = dijelovi[1].strip()

                    # Mod
                    if "CW" in str_data_full.upper(): mode = "CW"
                    elif "SSB" in str_data_full.upper(): mode = "SSB"
                    else: mode = "DIGI"

                    # Precizno izvlačenje pozivnog znaka
                    words = str_data_full.replace("|", " ").split()
                    possible_calls = []
                    for w in words:
                        w_clean = w.strip("[],'\"")
                        if any(c.isdigit() for c in w_clean) and any(c.isalpha() for c in w_clean):
                            if "." not in w_clean and "-" not in w_clean and w_clean not in ["CW", "DIGI", "SSB"]:
                                possible_calls.append(w_clean)

                    if possible_calls:
                        call = possible_calls[0]
                    elif len(dijelovi) >= 4:
                        call = dijelovi[3].strip()

                    if rda_matches:
                        rda = " ".join(list(set(rda_matches)))
                    else:
                        rda = "-"

                    if rda and rda != "-":
                        band_key, band_name = self.get_band_info(freq)
                        status_text, is_needed, is_all_time_new = self.check_slot_status_multi(rda, band_key, band_name)
                        
                        spot_entry = {
                            'time_epoch': time.time(),
                            'time_str': time_spot,
                            'call': call,
                            'freq': freq,
                            'band': band_name,
                            'mode': mode,
                            'rda': rda,
                            'status': status_text,
                            'is_new': is_needed
                        }
                        
                        with open("rda_dtb.txt", "a", encoding="utf-8") as f:
                            f.write(f"{time_spot}, {call}, {freq}, {mode}, {rda}\n")

                        self.root.after(0, lambda: self.add_cluster_spot_to_ui(spot_entry, is_all_time_new))

                except Exception as err:
                    print(f"Greška kod parsiranja cluster spota: {err}")

        def run_sio():
            url = "http://rdacabinet.ru/?call=9A5CW&filter=all"
            try:
                self.sio.connect(url, socketio_path="/socket.io/", transports=["websocket", "polling"])
                self.sio.wait()
            except Exception as e:
                print(f"Socket.io greška: {e}")

        threading.Thread(target=run_sio, daemon=True).start()

    def add_cluster_spot_to_ui(self, spot, is_all_time_new):
        self.cluster_spots.insert(0, spot)
        
        now = time.time()
        self.cluster_spots = [s for s in self.cluster_spots if now - s['time_epoch'] <= 1800]

        self.refresh_bottom_table()

        if spot['is_new'] and not self.hide_popup_var.get():
            bg = "#ffcccc" if is_all_time_new else "#ccffcc"
            title = "ALL-TIME-NEW RDA!" if is_all_time_new else "Novi RDA Band!"
            self.prikazi_cluster_alert(spot['call'], spot['rda'], spot['freq'], spot['band'], spot['mode'], spot['status'], title, bg)

    def refresh_bottom_table(self):
        for item in self.tree_bot.get_children():
            self.tree_bot.delete(item)

        now = time.time()
        self.cluster_spots = [s for s in self.cluster_spots if now - s['time_epoch'] <= 1800]

        only_new = self.filter_only_new_var.get()

        for spot in self.cluster_spots:
            if only_new and not spot['is_new']:
                continue

            tag = 'new_rda' if 'NOVA' in spot['status'] else ('slot_rda' if 'Novi' in spot['status'] else 'normal')
            self.tree_bot.insert("", tk.END, values=(
                spot['time_str'],
                spot['call'],
                spot['freq'],
                spot['band'],
                spot['mode'],
                spot['rda'],
                spot['status']
            ), tags=(tag,))

        self.tree_bot.tag_configure('new_rda', background='#331111')
        self.tree_bot.tag_configure('slot_rda', background='#113311')

    def prikazi_cluster_alert(self, call, rda, freq, band, mode, status_msg, title, bg_color):
        self.root.bell()
        popup = ctk.CTkToplevel(self.root)
        popup.title(title)
        try: popup.iconbitmap(resource_path('tnxqso2.ico'))
        except: pass
        popup.geometry("400x170")
        popup.attributes("-topmost", True)
        x, y = self.root.winfo_x() + 50, self.root.winfo_y() + 50
        popup.geometry(f"+{x}+{y}")
        
        ctk.CTkLabel(popup, text=title, font=("Arial", 12, "bold"), text_color="red" if "ALL" in title else "lightgreen").pack(pady=10)
        ctk.CTkLabel(popup, text=f"Stanica: {call}  |  Oblast(i): {rda}", font=("Arial", 11, "bold")).pack(pady=2)
        ctk.CTkLabel(popup, text=f"Frekvencija: {freq} kHz ({band})  |  Mod: {mode}", font=("Arial", 10)).pack(pady=2)
        ctk.CTkLabel(popup, text=status_msg, text_color="lightblue", font=("Arial", 10, "bold")).pack(pady=5)
        
        popup.after(15000, popup.destroy)

    def get_last_qso_info(self, callsign):
        try:
            clean_call = callsign.split('/')[0].lower()
            log_url = f"{URL_LOG_BASE}{clean_call}/log.json"
            r = requests.get(log_url, timeout=3)
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    last = data[0]
                    return f"{last.get('time', '')}   - {last.get('cs', '???')}"
        except: pass
        return "-"

    def find_rda(self, obj):
        str_obj = str(obj)
        matches = re.findall(r'[A-Z]{2}-\d{2,3}', str_obj)
        return " ".join(list(set(matches))) if matches else "-"

    def find_freq(self, obj):
        str_obj = str(obj)
        value_match = re.search(r"'value':\s*'([\d.]+)'", str_obj)
        if value_match:
            val = value_match.group(1)
            if val not in ["0.0", "0"]: return val
        match = re.search(r'\b([1-9]\d{3,4}\.\d)\b', str_obj)
        if match: return match.group(1)
        return "-"

    def update_loop(self):
        threading.Thread(target=self.fetch_all_data, daemon=True).start()
        self.refresh_bottom_table()
        self.root.after(REFRESH_MS, self.update_loop)

    def fetch_all_data(self):
        try:
            r = requests.get(f"{URL_MAIN}?t={int(time.time())}", timeout=10)
            if r.status_code == 200:
                stations = r.json()
                processed_list = []
                for s in stations:
                    call = str(s.get('callsign') or "???")
                    freq = self.find_freq(s)
                    band_key, band_name = self.get_band_info(freq)
                    rda = self.find_rda(s)
                    
                    slot_msg, is_needed, _ = self.check_slot_status_multi(rda, band_key, band_name)
                    last_qso = self.get_last_qso_info(call)
                    
                    processed_list.append((call, freq, rda, slot_msg, last_qso, is_needed))
                self.root.after(0, self.render_top_data, processed_list)
        except: pass

    def render_top_data(self, data_list):
        items_u_tablici = {self.tree_top.item(i)['values'][0]: i for i in self.tree_top.get_children()}
        
        for call, freq, rda, slot_msg, last_qso, is_needed in data_list:
            
            # 1. ORIGINALNI ALERT ZA 9A5CW U LOGU
            if "9A5CW" in last_qso:
                if call not in self.last_qso_seen or self.last_qso_seen[call] != last_qso:
                    self.alert_moj_znak(call, last_qso)
                    self.last_qso_seen[call] = last_qso
            
            # 2. ORIGINALNI QSY ALERT (Kada stanica promijeni frekvenciju)
            if call in self.last_data:
                if (freq != "-" and freq != self.last_data[call]['f'] and self.last_data[call]['f'] != "-"):
                    if not self.hide_popup_var.get():
                        self.prikazi_qsy_alert(call, freq, rda)
            
            self.last_data[call] = {'f': freq, 'r': rda}

            values = (call, freq, rda, slot_msg, last_qso)
            tag = 'needed_top' if is_needed else 'normal_top'

            if call in items_u_tablici:
                self.tree_top.item(items_u_tablici[call], values=values, tags=(tag,))
                del items_u_tablici[call]
            else:
                self.tree_top.insert("", tk.END, values=values, tags=(tag,))
                
        for r_id in items_u_tablici.values(): 
            self.tree_top.delete(r_id)

        # Konfiguracija boja za gornju tablicu (crveno za nove oblasti/bandove)
        self.tree_top.tag_configure('needed_top', foreground='#ff4444', font=("Arial", 9, "bold"))
        self.tree_top.tag_configure('normal_top', foreground='#ffffff', font=("Arial", 9))
            
        self.status_bar.configure(text=f"Auto Refresh: {time.strftime('%H:%M:%S')} | Matrični CSV: {len(self.rda_data_db)} oblasti | Cluster spotova: {len(self.cluster_spots)}")

    # --- ORIGINALNI ALERT METODE ---
    def alert_moj_znak(self, stanica, qso_info):
        self.root.bell()
        popup = ctk.CTkToplevel(self.root)
        popup.title("MOJ QSO!")
        popup.geometry("300x120")
        popup.attributes("-topmost", True)
        x, y = self.root.winfo_x() + 30, self.root.winfo_y() + 30
        popup.geometry(f"+{x}+{y}")
        
        ctk.CTkLabel(popup, text="!!! 9A5CW U LOGU !!!", text_color="lightgreen", font=("Arial", 12, "bold")).pack(pady=10)
        ctk.CTkLabel(popup, text=f"Stanica {stanica} te upisala:", font=("Arial", 10)).pack()
        ctk.CTkLabel(popup, text=f"{qso_info}", font=("Arial", 10, "italic"), text_color="yellow").pack(pady=5)
        popup.after(20000, popup.destroy)

    def prikazi_qsy_alert(self, call, freq, rda):
        self.root.bell()
        popup = ctk.CTkToplevel(self.root)
        popup.title("QSY!")
        popup.geometry("250x100")
        popup.attributes("-topmost", True)
        x, y = self.root.winfo_x() + 20, self.root.winfo_y() + 20
        popup.geometry(f"+{x}+{y}")
        
        ctk.CTkLabel(popup, text=f"Stanica: {call}", font=("Arial", 10, "bold"), text_color="red").pack(pady=5)
        ctk.CTkLabel(popup, text=f"{freq} kHz | {rda}", font=("Arial", 9)).pack()
        popup.after(15000, popup.destroy)

    def on_top_table_click(self, event):
        region = self.tree_top.identify("region", event.x, event.y)
        if region == "cell":
            column = self.tree_top.identify_column(event.x) 
            item_id = self.tree_top.identify_row(event.y)
            if not item_id: return
            
            row_values = self.tree_top.item(item_id, 'values')
            call = row_values[0]
            rda_full = row_values[2]
            
            if column == "#1":
                clean_call = call.split('/')[0].lower()
                url = f"{URL_LOG_BASE}{clean_call}/#/log"
                webbrowser.open(url)
            elif column == "#3":
                rdas = [r.strip() for r in rda_full.split() if r.strip() != "-"]
                if rdas:
                    self.show_all_rda_matrices(call, rdas)

    def on_bottom_table_click(self, event):
        region = self.tree_bot.identify("region", event.x, event.y)
        if region == "cell":
            column = self.tree_bot.identify_column(event.x)
            item_id = self.tree_bot.identify_row(event.y)
            if not item_id: return
            row_values = self.tree_bot.item(item_id, 'values')
            call = row_values[1]
            rda_full = row_values[5]
            
            if column == "#2":
                clean_call = call.split('/')[0].lower()
                webbrowser.open(f"{URL_LOG_BASE}{clean_call}/#/log")
            elif column == "#6":
                rdas = [r.strip() for r in rda_full.split() if r.strip() != "-"]
                if rdas:
                    self.show_all_rda_matrices(call, rdas)

    def show_all_rda_matrices(self, call, rdas):
        popup = ctk.CTkToplevel(self.root)
        popup.title(f"RDA Cab Matrix za stanicu: {call}")
        try: popup.iconbitmap(resource_path('tnxqso2.ico'))
        except: pass
        popup.geometry("580x600")
        popup.attributes("-topmost", True)
        
        canvas = tk.Canvas(popup, bg="#2b2b2b", highlightthickness=0)
        scrollbar = ttk.Scrollbar(popup, orient="vertical", command=canvas.yview)
        scrollable_frame = ctk.CTkFrame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ctk.CTkLabel(scrollable_frame, text=f"Pregled referenci za stanicu: {call}", font=("Arial", 11, "bold")).pack(pady=5)

        bands = ["1.8", "3.5", "7", "10", "14", "18", "21", "24", "28"]
        modes = ["CW", "SSB", "DIGI"]

        for rda in rdas:
            frame_rda = ctk.CTkFrame(scrollable_frame)
            frame_rda.pack(fill="x", padx=10, pady=5)

            ctk.CTkLabel(frame_rda, text=f"Oblast: {rda}", font=("Arial", 10, "bold")).pack(anchor="w", padx=5, pady=2)
            grid_frame = ctk.CTkFrame(frame_rda)
            grid_frame.pack(padx=5, pady=5)

            ctk.CTkLabel(grid_frame, text="Mod / Band", font=("Arial", 8, "bold"), width=70, fg_color="#333333").grid(row=0, column=0, padx=1, pady=1)
            for col_idx, b in enumerate(bands):
                ctk.CTkLabel(grid_frame, text=f"{b}M", font=("Arial", 8, "bold"), width=45, fg_color="#333333").grid(row=0, column=col_idx+1, padx=1, pady=1)

            row_data = self.rda_data_db.get(rda, {})

            for row_idx, mode in enumerate(modes):
                r_idx = row_idx + 1
                ctk.CTkLabel(grid_frame, text=mode, font=("Arial", 8, "bold"), width=70, fg_color="#333333").grid(row=r_idx, column=0, sticky="nsew", padx=1, pady=1)
                for col_idx, b in enumerate(bands):
                    c_idx = col_idx + 1
                    cell_val = row_data.get(b, "").upper()
                    has_slot = mode in cell_val

                    bg_c = "green" if has_slot else "#222222"
                    txt_c = "white" if has_slot else "gray"
                    lbl_text = "OK" if has_slot else "-"

                    lbl = ctk.CTkLabel(grid_frame, text=lbl_text, text_color=txt_c, fg_color=bg_c, font=("Arial", 9, "bold"), width=45)
                    lbl.grid(row=r_idx, column=c_idx, padx=1, pady=1)

        ctk.CTkLabel(scrollable_frame, text="Zeleno = Potvrđeno | Tamno = Nedostaje", text_color="lightgreen", font=("Arial", 9)).pack(pady=5)
        ctk.CTkButton(scrollable_frame, text="Zatvori", command=popup.destroy).pack(pady=5)

if __name__ == "__main__":
    download_latest_rda_csv()

    root = ctk.CTk()
    try:
        root.iconbitmap(resource_path('tnxqso2.ico'))
    except:
        print("Ikona 'tnxqso2.ico' nije pronađena, koristi se default.")
        
    app = App(root)
    root.mainloop()